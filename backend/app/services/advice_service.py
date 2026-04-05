import json
import logging
from dataclasses import asdict
from datetime import date
from types import SimpleNamespace

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AnnualDividend,
    AnnualFundamental,
    AdviceReport,
    Alert,
    CashBalance,
    FinancialSnapshot,
    MarketSnapshot,
    PortfolioHealthSnapshot,
    PortfolioPosition,
    SymbolRule,
    User,
    UserRule,
    WatchlistSymbol,
)
from app.services.ai_policy import AiPolicy
from app.services.gemini_client import generate_text
from app.services.notifier import send_email_notification, send_in_app_notification
from app.services.rule_engine import (
    SymbolDecisionResult,
    assess_annual_quality,
    decide_action,
    portfolio_health_check,
)
from app.utils import stable_hash


logger = logging.getLogger(__name__)
PRICE_UNIT_VND = 1000
BOARD_LOT_SIZE = 100


class AdviceService:
    def __init__(self) -> None:
        self.policy = AiPolicy()
        self.settings = get_settings()

    def run_for_all_users(self, db: Session, run_date: date) -> dict:
        users = db.execute(select(User)).scalars().all()
        details = {"run_date": run_date.isoformat(), "total_users": len(users), "generated": 0, "errors": []}

        for user in users:
            try:
                report = self.run_for_user(db, user.id, run_date)
                details["generated"] += 1
                logger.info(
                    "advice_generated user_id=%s report_date=%s used_ai=%s",
                    user.id,
                    run_date,
                    report.used_ai,
                )
            except Exception as exc:
                logger.exception("advice_run_failed user_id=%s", user.id)
                details["errors"].append(f"user={user.id}:{exc}")

        db.commit()
        return details

    def run_for_user(self, db: Session, user_id: int, run_date: date) -> AdviceReport:
        user = db.get(User, user_id)
        if not user:
            raise ValueError(f"User not found: {user_id}")

        watchlist_symbols = [w.symbol.upper() for w in db.execute(
            select(WatchlistSymbol).where(WatchlistSymbol.user_id == user_id, WatchlistSymbol.is_active.is_(True))
        ).scalars().all()]
        positions = db.execute(select(PortfolioPosition).where(PortfolioPosition.user_id == user_id)).scalars().all()
        symbol_rules = db.execute(select(SymbolRule).where(SymbolRule.user_id == user_id)).scalars().all()
        symbol_rule_map = {sr.symbol.upper(): sr for sr in symbol_rules}

        if not watchlist_symbols and positions:
            watchlist_symbols = sorted({p.symbol.upper() for p in positions})

        rule = db.execute(select(UserRule).where(UserRule.user_id == user_id)).scalar_one_or_none()
        if not rule:
            rule = UserRule(user_id=user_id)
            db.add(rule)
            db.flush()

        cash_row = db.execute(select(CashBalance).where(CashBalance.user_id == user_id)).scalar_one_or_none()
        cash = float(cash_row.cash if cash_row else 0)

        decisions: list[SymbolDecisionResult] = []
        market_by_symbol = {}
        annual_checks_by_symbol: dict[str, dict] = {}
        previous_report = self.policy.get_latest_report(db, user_id)
        if previous_report:
            try:
                previous_payload = json.loads(previous_report.deterministic_payload_json)
            except Exception:
                previous_payload = {}
        else:
            previous_payload = {}

        for symbol in watchlist_symbols:
            market_row = db.execute(
                select(MarketSnapshot)
                .where(MarketSnapshot.symbol == symbol, MarketSnapshot.snapshot_date <= run_date)
                .order_by(desc(MarketSnapshot.snapshot_date))
                .limit(1)
            ).scalar_one_or_none()
            financial_row = db.execute(
                select(FinancialSnapshot)
                .where(FinancialSnapshot.symbol == symbol, FinancialSnapshot.snapshot_date <= run_date)
                .order_by(desc(FinancialSnapshot.snapshot_date))
                .limit(1)
            ).scalar_one_or_none()

            if not market_row:
                continue

            if not financial_row:
                financial_row = SimpleNamespace(
                    pe=None,
                    pb=None,
                    roe=None,
                    roa=None,
                    debt_to_equity=None,
                    current_ratio=None,
                    operating_cash_flow=None,
                    free_cash_flow=None,
                    revenue_growth=None,
                    profit_growth=None,
                    eps=None,
                    auditor_opinion=None,
                )

            market_by_symbol[symbol] = market_row
            current_pos = next((p for p in positions if p.symbol.upper() == symbol), None)
            symbol_rule = symbol_rule_map.get(symbol)
            decision = decide_action(
                symbol=symbol,
                market_row=market_row,
                financial_row=financial_row,
                margin_safety=float(rule.value_margin_safety),
                stop_accumulate=(
                    symbol_rule.stop_accumulate_price
                    if symbol_rule and symbol_rule.stop_accumulate_price is not None
                    else None
                ),
                take_profit=(
                    symbol_rule.take_profit_price
                    if symbol_rule and symbol_rule.take_profit_price is not None
                    else None
                ),
                position_quantity=float(current_pos.quantity if current_pos else 0),
                avg_cost=float(current_pos.avg_cost if current_pos else 0),
            )

            annual_fundamentals = db.execute(
                select(AnnualFundamental)
                .where(AnnualFundamental.symbol == symbol)
                .order_by(desc(AnnualFundamental.fiscal_year))
                .limit(15)
            ).scalars().all()
            annual_dividends = db.execute(
                select(AnnualDividend)
                .where(AnnualDividend.symbol == symbol)
                .order_by(desc(AnnualDividend.fiscal_year))
                .limit(15)
            ).scalars().all()
            annual_check = assess_annual_quality(annual_fundamentals, annual_dividends)
            annual_checks_by_symbol[symbol] = annual_check

            annual_reasons = annual_check.get("reasons", [])
            annual_warnings = annual_check.get("warnings", [])
            for reason in annual_reasons[:2]:
                decision.reasons.append(reason)
            if annual_warnings:
                decision.reasons.append(annual_warnings[0])

            if annual_check.get("has_major_hole"):
                decision.risk_score = min(100.0, decision.risk_score + 10)
                decision.confidence = max(35.0, decision.confidence - 12)
            elif annual_check.get("integrity_ok"):
                decision.confidence = min(95.0, decision.confidence + 4)

            buy_extra_margin = float(rule.buy_zone_extra_margin or 0)
            if buy_extra_margin > 1:
                buy_extra_margin = buy_extra_margin / 100
            if decision.action == "BUY_ZONE" and decision.buy_zone > 0 and buy_extra_margin > 0:
                strict_buy_price = decision.buy_zone * (1 - buy_extra_margin)
                if decision.current_price > strict_buy_price:
                    decision.action = "HOLD"
                    decision.reasons = [
                        r for r in decision.reasons if "Giá đang nằm trong vùng mua theo biên an toàn" not in r
                    ]
                    decision.reasons.insert(
                        0,
                        (
                            f"Điều kiện mua thêm: giá <= {strict_buy_price:.2f} (nghìn/cp) với biên {buy_extra_margin * 100:.1f}%. "
                            f"Giá hiện tại {decision.current_price:.2f} nên chưa mua"
                        ),
                    )
            if decision.action == "BUY_ZONE":
                decision.disbursement_ratio = 1.0
                decision.reasons.insert(0, "Phân bổ giải ngân theo tiền mặt khả dụng hiện tại")

            decision.reasons = list(dict.fromkeys(decision.reasons))[:8]
            decisions.append(decision)

        decisions = sorted(decisions, key=lambda x: (x.score - x.risk_score), reverse=True)

        risk_score, warnings, suggestions, metrics = portfolio_health_check(
            positions=positions,
            market_by_symbol=market_by_symbol,
            max_position_weight=float(rule.max_position_weight),
            target_cash_ratio=float(rule.target_cash_ratio),
            cash=cash,
        )

        symbols_with_holes = [s for s, v in annual_checks_by_symbol.items() if v.get("has_major_hole")]
        symbols_with_good_integrity = [s for s, v in annual_checks_by_symbol.items() if v.get("integrity_ok")]
        if symbols_with_holes:
            warnings.append(
                "Cần soi kỹ lỗ hổng BCTC ở: " + ", ".join(symbols_with_holes[:5])
            )
        if symbols_with_good_integrity:
            suggestions.append(
                "Ưu tiên theo dõi doanh nghiệp có lịch sử ổn định: " + ", ".join(symbols_with_good_integrity[:5])
            )

        total_assets = float(metrics.get("total_assets", 0) or 0)
        stock_ratio = float(metrics.get("stock_ratio", 0) or 0)
        target_stock_ratio = float(metrics.get("target_stock_ratio", 0) or 0)
        balance_tolerance = float(rule.allocation_balance_tolerance or 0.02)
        if balance_tolerance > 1:
            balance_tolerance = balance_tolerance / 100

        stock_ratio_low = max(0.0, target_stock_ratio - balance_tolerance)
        stock_ratio_high = min(1.0, target_stock_ratio + balance_tolerance)
        for decision in decisions:
            if decision.action == "BUY_ZONE" and stock_ratio >= stock_ratio_low:
                decision.action = "HOLD"
                decision.disbursement_ratio = 0.0
                decision.reasons = [
                    r for r in decision.reasons if "Giá đang nằm trong vùng mua theo biên an toàn" not in r
                ]
                decision.reasons.insert(
                    0,
                    (
                        f"Danh mục đang gần cân bằng tiền/cổ phiếu "
                        f"({stock_ratio * 100:.1f}% cổ phiếu, mục tiêu {target_stock_ratio * 100:.1f}% "
                        f"± {balance_tolerance * 100:.1f}%)"
                    ),
                )
            elif decision.action == "SELL_ZONE" and stock_ratio <= stock_ratio_high:
                decision.action = "HOLD"
                decision.reasons = [
                    r for r in decision.reasons if "Giá đã tiến vào vùng chốt lời định giá" not in r
                ]
                decision.reasons.insert(
                    0,
                    (
                        f"Danh mục chưa vượt nhiều so với mục tiêu cổ phiếu "
                        f"({stock_ratio * 100:.1f}% hiện tại, ngưỡng bán khi > {stock_ratio_high * 100:.1f}%)"
                    ),
                )

        self._allocate_buy_recommendations(decisions=decisions, total_assets=total_assets, cash_available=cash)

        top_decisions = decisions[: self.settings.ai_top_symbols_per_report]

        payload = {
            "report_date": run_date.isoformat(),
            "decisions": [asdict(d) for d in decisions],
            "portfolio": {
                "risk_score": risk_score,
                "warnings": warnings,
                "suggestions": suggestions,
                "metrics": metrics,
                "target_cash_ratio": rule.target_cash_ratio,
                "max_position_weight": rule.max_position_weight,
                "buy_zone_extra_margin": rule.buy_zone_extra_margin,
                "allocation_balance_tolerance": rule.allocation_balance_tolerance,
                "disbursement_policy": "cash_available_split",
                "annual_checks_by_symbol": annual_checks_by_symbol,
            },
        }
        ai_payload = {
            "report_date": payload["report_date"],
            "decisions": [asdict(d) for d in top_decisions],
            "portfolio": payload["portfolio"],
        }

        max_score_delta = self._get_max_delta(previous_payload, payload, "score")
        max_risk_delta = self._get_max_delta(previous_payload, payload, "risk_score")
        state_hash = stable_hash(payload)

        material_change = self.policy.is_material_change(
            latest_report=previous_report,
            state_hash=state_hash,
            max_score_delta=max_score_delta,
            max_risk_delta=max_risk_delta,
        )

        should_call_ai, reason = self.policy.should_call_ai(
            db=db,
            user_id=user_id,
            run_date=run_date,
            state_hash=state_hash,
            material_change=material_change,
        )

        summary = self._build_template_summary(top_decisions, risk_score, warnings)
        ai_text = None
        used_ai = False
        latency_ms = 0
        ai_error = None

        if should_call_ai:
            prompt = self._build_ai_prompt(user, ai_payload)
            try:
                ai_text, latency_ms = generate_text(prompt)
                used_ai = True
            except Exception as exc:
                ai_error = str(exc)
                logger.exception("ai_generation_failed user_id=%s", user_id)
                ai_text = self._build_ai_fallback_text(top_decisions, warnings, suggestions)

            self.policy.log_usage(
                db=db,
                user_id=user_id,
                run_date=run_date,
                purpose="daily_advice",
                state_hash=state_hash,
                success=used_ai,
                latency_ms=latency_ms,
                error_message=ai_error,
            )
        else:
            logger.info("ai_skipped user_id=%s reason=%s", user_id, reason)

        existing = db.execute(
            select(AdviceReport).where(AdviceReport.user_id == user_id, AdviceReport.report_date == run_date)
        ).scalar_one_or_none()

        confidence = 0.0
        if top_decisions:
            confidence = round(sum(d.confidence for d in top_decisions) / len(top_decisions), 2)

        if existing:
            existing.summary = summary
            existing.deterministic_payload_json = json.dumps(payload, ensure_ascii=False)
            existing.ai_text = ai_text
            existing.used_ai = used_ai
            existing.confidence = confidence
            existing.state_hash = state_hash
            report = existing
        else:
            report = AdviceReport(
                user_id=user_id,
                report_date=run_date,
                summary=summary,
                deterministic_payload_json=json.dumps(payload, ensure_ascii=False),
                ai_text=ai_text,
                used_ai=used_ai,
                confidence=confidence,
                state_hash=state_hash,
            )
            db.add(report)

        self._update_health_snapshot(db, user_id, run_date, risk_score, warnings, suggestions)
        self._emit_alerts(db, user_id, top_decisions)
        self._emit_allocation_alert(db, user_id, metrics)

        send_in_app_notification(user_id, f"Khuyến nghị {run_date.isoformat()}", summary)
        send_email_notification(
            to_email=user.email,
            subject=f"[KyLuat DauTu] Khuyến nghị {run_date.isoformat()}",
            body=f"{summary}\n\n{ai_text or ''}",
        )

        return report

    @staticmethod
    def _get_max_delta(previous_payload: dict, current_payload: dict, field: str) -> float:
        prev_decisions = {
            d["symbol"]: d
            for d in previous_payload.get("decisions", [])
            if isinstance(d, dict) and "symbol" in d
        }
        max_delta = 0.0
        for current in current_payload.get("decisions", []):
            symbol = current["symbol"]
            prev = prev_decisions.get(symbol)
            if prev is None:
                max_delta = max(max_delta, 99.0)
            else:
                max_delta = max(max_delta, abs(float(current.get(field, 0)) - float(prev.get(field, 0))))
        return round(max_delta, 2)

    @staticmethod
    def _build_template_summary(decisions: list[SymbolDecisionResult], risk_score: float, warnings: list[str]) -> str:
        if not decisions:
            return "Chưa có dữ liệu đủ để tạo khuyến nghị. Hãy chạy ETL 15:30 hoặc bổ sung watchlist."

        buy_candidates = [d.symbol for d in decisions if d.action == "BUY_ZONE"]
        sell_candidates = [d.symbol for d in decisions if d.action == "SELL_ZONE"]

        head = f"Top cơ hội: {', '.join(d.symbol for d in decisions[:3])}."
        body = []
        body.append(f"Rủi ro danh mục hiện tại: {risk_score:.1f}/100.")
        if buy_candidates:
            body.append(f"Vùng mua kỷ luật: {', '.join(buy_candidates)}.")
            planned = [
                f"{d.symbol} ~ {d.final_disbursement_value:,.0f} ₫"
                for d in decisions
                if d.action == "BUY_ZONE" and d.final_disbursement_value > 0
            ]
            if planned:
                body.append("Giải ngân đề xuất (theo tiền mặt khả dụng): " + ", ".join(planned[:3]) + ".")
        if sell_candidates:
            body.append(f"Vùng chốt lời: {', '.join(sell_candidates)}.")
        if warnings:
            body.append(f"Cảnh báo: {warnings[0]}")
        body.append("Giá mua/bán chỉ là gợi ý định lượng, quyết định cuối cùng thuộc về bạn.")
        return " ".join([head] + body)

    @staticmethod
    def _build_ai_fallback_text(decisions: list[SymbolDecisionResult], warnings: list[str], suggestions: list[str]) -> str:
        lines = ["AI tạm thời không khả dụng, hệ thống dùng bản phân tích định lượng."]
        for d in decisions[:3]:
            lines.append(
                f"- {d.symbol}: {d.action}, score {d.score}, risk {d.risk_score}, buy {d.buy_zone} (nghin), sell {d.sell_zone} (nghin), goi y giai ngan {d.final_disbursement_value:,.0f} ₫."
            )
        if warnings:
            lines.append(f"- Cảnh báo chính: {warnings[0]}.")
        if suggestions:
            lines.append(f"- Gợi ý: {suggestions[0]}.")
        return "\n".join(lines)

    @staticmethod
    def _build_ai_prompt(user: User, payload: dict) -> str:
        return (
            "Bạn là trợ lý đầu tư giá trị, luôn nhấn mạnh kỷ luật và không thay người dùng quyết định.\n"
            "Hãy viết ngắn gọn bản tin sáng cho nhà đầu tư Việt Nam.\n"
            "Yêu cầu:\n"
            "1) Nêu 3 ý quan trọng nhất từ dữ liệu.\n"
            "2) Nêu giá vùng mua/bán chỉ mang tính tham khảo định lượng.\n"
            "3) Khi nói về giải ngân phải ghi rõ mức đề xuất dựa trên tiền mặt khả dụng hiện tại.\n"
            "4) Nhắc tuân thủ rule chốt lời/ngừng tích sản đã đặt.\n"
            "5) Không dùng giọng khẳng định chắc chắn thắng.\n"
            f"Nhà đầu tư: {user.full_name}.\n"
            f"Dữ liệu JSON: {json.dumps(payload, ensure_ascii=False)}"
        )

    @staticmethod
    def _update_health_snapshot(
        db: Session,
        user_id: int,
        run_date: date,
        risk_score: float,
        warnings: list[str],
        suggestions: list[str],
    ) -> None:
        existing = db.execute(
            select(PortfolioHealthSnapshot).where(
                PortfolioHealthSnapshot.user_id == user_id,
                PortfolioHealthSnapshot.snapshot_date == run_date,
            )
        ).scalar_one_or_none()

        if existing:
            existing.risk_score = risk_score
            existing.warnings_json = json.dumps(warnings, ensure_ascii=False)
            existing.suggestions_json = json.dumps(suggestions, ensure_ascii=False)
            return

        db.add(
            PortfolioHealthSnapshot(
                user_id=user_id,
                snapshot_date=run_date,
                risk_score=risk_score,
                warnings_json=json.dumps(warnings, ensure_ascii=False),
                suggestions_json=json.dumps(suggestions, ensure_ascii=False),
            )
        )

    @staticmethod
    def _emit_alerts(db: Session, user_id: int, decisions: list[SymbolDecisionResult]) -> None:
        for decision in decisions:
            if decision.action not in {"BUY_ZONE", "SELL_ZONE"}:
                continue

            if decision.action == "BUY_ZONE" and decision.final_disbursement_quantity < BOARD_LOT_SIZE:
                continue

            if decision.action == "BUY_ZONE":
                alert_type = "buy_signal"
                message = (
                    f"{decision.symbol}: giá {decision.current_price} (nghìn đồng/cp) vào vùng mua {decision.buy_zone}. "
                    f"Đề xuất giải ngân {decision.final_disbursement_value:,.0f} ₫ "
                    f"(~{decision.final_disbursement_quantity:,.0f} cp), theo tiền mặt khả dụng."
                )
                severity = "medium"
                trigger_price = decision.buy_zone
            else:
                alert_type = "sell_signal"
                message = (
                    f"{decision.symbol}: giá {decision.current_price} (nghìn đồng/cp) "
                    f"vào vùng chốt lời {decision.sell_zone}."
                )
                severity = "high"
                trigger_price = decision.sell_zone

            db.add(
                Alert(
                    user_id=user_id,
                    symbol=decision.symbol,
                    alert_type=alert_type,
                    message=message,
                    severity=severity,
                    trigger_price=trigger_price,
                    current_price=decision.current_price,
                )
            )

    @staticmethod
    def _emit_allocation_alert(db: Session, user_id: int, metrics: dict) -> None:
        stock_ratio = float(metrics.get("stock_ratio", 0) or 0)
        target_stock_ratio = float(metrics.get("target_stock_ratio", 0) or 0)
        gap = stock_ratio - target_stock_ratio

        if abs(gap) <= 0.01:
            return

        if gap < 0:
            alert_type = "allocation_buy_more"
            message = (
                f"Tỷ lệ cổ phiếu hiện tại {stock_ratio * 100:.1f}% thấp hơn mục tiêu {target_stock_ratio * 100:.1f}%. "
                "Cân nhắc mua thêm để đưa danh mục về tỷ lệ mục tiêu."
            )
            severity = "medium"
        else:
            alert_type = "allocation_sell_reduce"
            message = (
                f"Tỷ lệ cổ phiếu hiện tại {stock_ratio * 100:.1f}% cao hơn mục tiêu {target_stock_ratio * 100:.1f}%. "
                "Cân nhắc chốt bớt để đưa danh mục về tỷ lệ mục tiêu."
            )
            severity = "high"

        db.add(
            Alert(
                user_id=user_id,
                symbol="PORTFOLIO",
                alert_type=alert_type,
                message=message,
                severity=severity,
                trigger_price=None,
                current_price=None,
            )
        )

    @staticmethod
    def _allocate_buy_recommendations(
        decisions: list[SymbolDecisionResult],
        total_assets: float,
        cash_available: float,
    ) -> None:
        if total_assets <= 0:
            return

        buy_decisions = [d for d in decisions if d.action == "BUY_ZONE" and d.disbursement_ratio > 0]
        if not buy_decisions:
            return

        for decision in buy_decisions:
            planned_value = cash_available * decision.disbursement_ratio
            planned_quantity_raw = (planned_value / (decision.current_price * PRICE_UNIT_VND)) if decision.current_price > 0 else 0.0
            planned_quantity_lot = float(int(planned_quantity_raw // BOARD_LOT_SIZE) * BOARD_LOT_SIZE)
            decision.planned_disbursement_quantity = planned_quantity_lot
            decision.planned_disbursement_value = round(planned_quantity_lot * decision.current_price * PRICE_UNIT_VND, 2)

        total_planned = sum(d.planned_disbursement_value for d in buy_decisions)
        if total_planned <= 0:
            for decision in buy_decisions:
                decision.final_disbursement_value = 0.0
                decision.final_disbursement_quantity = 0.0
                decision.reasons.append(
                    f"Tiền mặt chưa đủ mua lô tối thiểu {BOARD_LOT_SIZE} cp theo giá hiện tại"
                )
            return

        scale = 1.0
        if cash_available <= 0:
            scale = 0.0
        elif total_planned > cash_available:
            scale = cash_available / total_planned

        for decision in buy_decisions:
            final_value = decision.planned_disbursement_value * scale
            final_quantity_raw = (final_value / (decision.current_price * PRICE_UNIT_VND)) if decision.current_price > 0 else 0.0
            final_quantity_lot = float(int(final_quantity_raw // BOARD_LOT_SIZE) * BOARD_LOT_SIZE)
            decision.final_disbursement_quantity = final_quantity_lot
            decision.final_disbursement_value = round(final_quantity_lot * decision.current_price * PRICE_UNIT_VND, 2)

            if decision.final_disbursement_quantity <= 0:
                decision.reasons.append(
                    f"Tiền mặt chưa đủ mua lô tối thiểu {BOARD_LOT_SIZE} cp theo giá hiện tại"
                )
            if scale < 0.999:
                decision.reasons.append("Đã co giãn đề xuất do giới hạn tiền mặt hiện tại")
