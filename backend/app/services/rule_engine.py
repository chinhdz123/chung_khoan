import json
from dataclasses import dataclass

PRICE_UNIT_VND = 1000


@dataclass
class SymbolDecisionResult:
    symbol: str
    score: float
    risk_score: float
    confidence: float
    action: str
    current_price: float
    buy_zone: float
    sell_zone: float
    reasons: list[str]
    disbursement_ratio: float = 0.0
    planned_disbursement_value: float = 0.0
    final_disbursement_value: float = 0.0
    planned_disbursement_quantity: float = 0.0
    final_disbursement_quantity: float = 0.0


def _safe(value: float | None, default: float) -> float:
    return default if value is None else float(value)


def _normalize_percent_like(raw: float) -> float:
    value = float(raw)
    # Some sources return ROE as ratio (0.18) while most rows are already percent (18).
    if value != 0 and abs(value) <= 1:
        return value * 100
    return value


def _normalize_eps_to_price_unit(eps_raw: float, close_price: float | None = None, pe: float | None = None) -> float:
    # UI/market price uses nghin dong/cp.
    # Prefer reconciling EPS with close/PE when available because some sources mix
    # VND and nghin-VND units for EPS across symbols.
    eps = float(eps_raw)
    if close_price and pe and close_price > 0 and pe > 0:
        implied_eps = close_price / pe
        candidates = [eps]
        if abs(eps) >= 1:
            candidates.append(eps / PRICE_UNIT_VND)
        return min(candidates, key=lambda x: abs(x - implied_eps))

    # Fallback heuristic when PE is missing/unusable.
    if abs(eps) >= 100:
        return eps / PRICE_UNIT_VND
    return eps


def intrinsic_value_from_financial(
    financial_row,
    margin_safety: float = 0.25,
    close_price: float | None = None,
) -> tuple[float, float, float]:
    eps_raw = _safe(financial_row.eps, 1500)
    pe = _safe(financial_row.pe, 0)
    eps = _normalize_eps_to_price_unit(eps_raw, close_price=close_price, pe=pe)
    roe = _normalize_percent_like(_safe(financial_row.roe, 12))
    pe_fair = max(8, min(18, roe / 1.5))
    intrinsic_eps = eps * pe_fair

    intrinsic_pb = 0.0
    pb = _safe(financial_row.pb, 0)
    if close_price and close_price > 0 and pb > 0:
        bvps = close_price / pb
        target_pb = max(0.7, min(1.8, roe / 12))
        intrinsic_pb = bvps * target_pb

    intrinsic = intrinsic_eps
    if intrinsic_pb > 0:
        outlier_eps = bool(
            close_price
            and close_price > 0
            and (intrinsic_eps <= 0 or intrinsic_eps < close_price * 0.2 or intrinsic_eps > close_price * 3)
        )
        if outlier_eps:
            intrinsic = intrinsic_pb
        else:
            intrinsic = (intrinsic_eps * 0.65) + (intrinsic_pb * 0.35)

    if close_price and close_price > 0:
        intrinsic = max(close_price * 0.35, min(close_price * 2.5, intrinsic))

    buy_zone = intrinsic * (1 - margin_safety)
    sell_zone = intrinsic * 1.12
    return intrinsic, buy_zone, sell_zone


def score_symbol(market_row, financial_row) -> tuple[float, float, list[str]]:
    pe = _safe(financial_row.pe, 15)
    pb = _safe(financial_row.pb, 1.8)
    roe = _normalize_percent_like(_safe(financial_row.roe, 12))
    debt = _safe(financial_row.debt_to_equity, 1.2)
    ocf = _safe(financial_row.operating_cash_flow, 0)
    foreign = _safe(market_row.foreign_net_value, 0)
    prop = _safe(market_row.proprietary_net_value, 0)

    valuation_score = 40
    valuation_score += 12 if pe < 12 else -8
    valuation_score += 8 if pb < 1.8 else -5

    quality_score = 30
    quality_score += 10 if roe > 15 else -5
    quality_score += 8 if ocf > 0 else -10

    flow_score = 20
    flow_score += 6 if foreign > 0 else -6
    flow_score += 6 if prop > 0 else -4

    risk_penalty = 0
    risk_penalty += 15 if debt > 2 else 0
    risk_penalty += 8 if ocf < 0 else 0

    raw_score = max(0, min(100, valuation_score + quality_score + flow_score - risk_penalty))
    risk_score = max(0, min(100, 35 + (debt * 20) + (10 if ocf < 0 else -5) + (5 if pe > 22 else 0)))

    reasons = []
    reasons.append("Định giá tương đối hấp dẫn" if pe < 14 else "Định giá chưa thật sự rẻ")
    reasons.append("ROE tốt" if roe > 15 else "ROE trung bình")
    reasons.append("Dòng tiền kinh doanh dương" if ocf > 0 else "Dòng tiền kinh doanh âm")
    reasons.append("Khối ngoại hỗ trợ" if foreign > 0 else "Khối ngoại chưa ủng hộ")

    return round(raw_score, 2), round(risk_score, 2), reasons


def decide_action(
    symbol: str,
    market_row,
    financial_row,
    margin_safety: float,
    stop_accumulate: float | None,
    take_profit: float | None,
    position_quantity: float,
    avg_cost: float,
) -> SymbolDecisionResult:
    margin_safety = _safe(margin_safety, 0.25)
    current_price = _safe(market_row.close_price, 0)
    _, buy_zone, sell_zone = intrinsic_value_from_financial(
        financial_row,
        margin_safety=margin_safety,
        close_price=current_price,
    )
    score, risk_score, reasons = score_symbol(market_row, financial_row)
    confidence = max(40, min(95, score - (risk_score * 0.35)))

    action = "HOLD"
    if current_price <= buy_zone and score >= 60:
        action = "BUY_ZONE"
        reasons.insert(0, "Giá đang nằm trong vùng mua theo biên an toàn")
    if position_quantity > 0 and current_price >= sell_zone and score < 75:
        action = "SELL_ZONE"
        reasons.insert(0, "Giá đã tiến vào vùng chốt lời định giá")

    if stop_accumulate and current_price >= stop_accumulate and action == "BUY_ZONE":
        action = "HOLD"
        reasons.insert(0, "Vượt ngưỡng ngừng tích sản do người dùng đặt")

    if take_profit and current_price >= take_profit and position_quantity > 0:
        action = "SELL_ZONE"
        reasons.insert(0, "Đạt ngưỡng chốt lời do người dùng đặt")

    if position_quantity > 0 and avg_cost > 0:
        pnl_pct = ((current_price - avg_cost) / avg_cost) * 100
        reasons.append(f"Lãi/lỗ tạm tính: {pnl_pct:.2f}%")

    return SymbolDecisionResult(
        symbol=symbol,
        score=score,
        risk_score=risk_score,
        confidence=round(confidence, 2),
        action=action,
        current_price=round(current_price, 2),
        buy_zone=round(buy_zone, 2),
        sell_zone=round(sell_zone, 2),
        reasons=reasons[:6],
    )


def portfolio_health_check(
    positions: list,
    market_by_symbol: dict,
    max_position_weight: float,
    target_cash_ratio: float,
    cash: float,
) -> tuple[float, list[str], list[str], dict]:
    warnings: list[str] = []
    suggestions: list[str] = []

    total_stock_value = 0.0
    position_values: dict[str, float] = {}
    for p in positions:
        symbol = p.symbol.upper()
        market_row = market_by_symbol.get(symbol)
        market_price = float(market_row.close_price) if market_row else 0.0
        cached_price = float(getattr(p, "current_price", 0) or 0)
        latest_price = market_price if market_price > 0 else cached_price
        if latest_price <= 0:
            continue
        value = float(p.quantity) * latest_price * PRICE_UNIT_VND
        position_values[symbol] = value
        total_stock_value += value

    total_assets = total_stock_value + cash
    risk_score = 25.0

    if total_assets <= 0:
        warnings.append("Danh mục chưa có dữ liệu giá trị để đánh giá")
        return 80.0, warnings, ["Bổ sung danh mục và chạy ETL ngày để nhận đánh giá"], {
            "total_stock_value": 0,
            "total_assets": cash,
            "cash_ratio": 1.0,
            "position_weights": {},
        }

    cash_ratio = cash / total_assets
    stock_ratio = max(0.0, min(1.0, 1 - cash_ratio))
    target_stock_ratio = max(0.0, min(1.0, 1 - target_cash_ratio))
    ratio_gap = stock_ratio - target_stock_ratio

    if ratio_gap < -0.01:
        warnings.append(
            f"Tỷ lệ cổ phiếu hiện tại {stock_ratio * 100:.1f}% thấp hơn mục tiêu {target_stock_ratio * 100:.1f}%, cân nhắc mua thêm"
        )
        suggestions.append("Có thể giải ngân thêm để đưa tỷ lệ cổ phiếu về gần mục tiêu")
        risk_score += 6
    elif ratio_gap > 0.01:
        warnings.append(
            f"Tỷ lệ cổ phiếu hiện tại {stock_ratio * 100:.1f}% cao hơn mục tiêu {target_stock_ratio * 100:.1f}%, cân nhắc giảm tỷ trọng"
        )
        suggestions.append("Có thể chốt bớt vị thế để hạ tỷ lệ cổ phiếu về gần mục tiêu")
        risk_score += 6

    if cash_ratio < target_cash_ratio * 0.5:
        warnings.append("Tỷ trọng tiền mặt thấp hơn nhiều so với mục tiêu, dễ giảm linh hoạt khi thị trường xấu")
        suggestions.append("Tăng dần tiền mặt bằng chốt lời từng phần ở mã đạt vùng định giá cao")
        risk_score += 8

    weights = {k: v / total_assets for k, v in position_values.items()}
    overweight = [f"{k} ({w * 100:.1f}%)" for k, w in weights.items() if w > max_position_weight]
    if overweight:
        warnings.append(f"Tập trung tỷ trọng cao: {', '.join(overweight)}")
        suggestions.append("Chia lệnh giải ngân thành nhiều mốc và giới hạn tỷ trọng mỗi mã")
        risk_score += 18

    if len(weights) < 3 and total_stock_value > 0:
        warnings.append("Danh mục ít mã, rủi ro tập trung ngành/mã")
        suggestions.append("Mở rộng danh mục tối thiểu 3-5 mã thuộc ngành khác nhau")
        risk_score += 8

    if not warnings:
        suggestions.append("Danh mục đang cân bằng tương đối, tiếp tục tuân thủ kỷ luật giải ngân")
        risk_score = max(12, risk_score - 8)

    metrics = {
        "total_stock_value": round(total_stock_value, 2),
        "total_assets": round(total_assets, 2),
        "cash_ratio": round(cash_ratio, 4),
        "stock_ratio": round(stock_ratio, 4),
        "target_cash_ratio": round(target_cash_ratio, 4),
        "target_stock_ratio": round(target_stock_ratio, 4),
        "stock_ratio_gap": round(ratio_gap, 4),
        "position_weights": {k: round(v, 4) for k, v in weights.items()},
    }
    return round(min(100, risk_score), 2), warnings, suggestions, metrics


def parse_disbursement_plan(raw_json: str) -> list[dict]:
    try:
        levels = json.loads(raw_json or "[]")
        if isinstance(levels, list):
            return levels
        return []
    except Exception:
        return []


def get_triggered_disbursement_ratio(current_price: float, levels: list[dict]) -> float:
    ratios: list[float] = []
    for item in levels:
        raw_price = item.get("price") if isinstance(item, dict) else None
        raw_ratio = item.get("ratio") if isinstance(item, dict) else None
        if raw_price is None or raw_ratio is None:
            continue
        try:
            price = float(raw_price)
            ratio = float(raw_ratio)
        except Exception:
            continue
        if price <= 0 or ratio <= 0:
            continue
        if current_price <= price:
            ratios.append(min(1.0, ratio))
    if not ratios:
        return 0.0
    return round(max(ratios), 4)


def assess_annual_quality(annual_fundamentals: list, annual_dividends: list) -> dict:
    years = sorted({int(getattr(r, "fiscal_year", 0) or 0) for r in annual_fundamentals if getattr(r, "fiscal_year", 0)}, reverse=True)
    total_years = len(years)

    profitable_years = 0
    positive_ocf_years = 0
    clean_audit_years = 0
    total_audit_years = 0
    red_flags: list[str] = []

    for row in annual_fundamentals:
        net_profit = getattr(row, "net_profit", None)
        operating_cf = getattr(row, "operating_cash_flow", None)
        if net_profit is not None and float(net_profit) > 0:
            profitable_years += 1
        if operating_cf is not None and float(operating_cf) > 0:
            positive_ocf_years += 1

        opinion = str(getattr(row, "auditor_opinion", "") or "").lower()
        if opinion:
            total_audit_years += 1
            bad_tokens = ["ngoại trừ", "không chấp nhận", "từ chối", "adverse", "disclaimer", "qualified"]
            if not any(token in opinion for token in bad_tokens):
                clean_audit_years += 1

        try:
            flags = json.loads(getattr(row, "red_flags_json", "[]") or "[]")
            if isinstance(flags, list):
                red_flags.extend([str(f) for f in flags if f])
        except Exception:
            pass

    profit_ratio = (profitable_years / total_years) if total_years else 0.0
    ocf_ratio = (positive_ocf_years / total_years) if total_years else 0.0
    clean_audit_ratio = (clean_audit_years / total_audit_years) if total_audit_years else 0.0

    dividend_rows = sorted(
        [d for d in annual_dividends if getattr(d, "fiscal_year", None)],
        key=lambda x: int(getattr(x, "fiscal_year", 0)),
        reverse=True,
    )
    paid_years = [int(getattr(d, "fiscal_year", 0)) for d in dividend_rows if (getattr(d, "cash_dividend_per_share", 0) or 0) > 0]
    avg_dividend = 0.0
    if paid_years:
        values = [float(getattr(d, "cash_dividend_per_share", 0) or 0) for d in dividend_rows[:5] if (getattr(d, "cash_dividend_per_share", 0) or 0) > 0]
        if values:
            avg_dividend = sum(values) / len(values)

    consecutive_dividend_years = 0
    if paid_years:
        expected = paid_years[0]
        for year in sorted(set(paid_years), reverse=True):
            if year == expected:
                consecutive_dividend_years += 1
                expected -= 1
            elif year < expected:
                break

    integrity_ok = total_years >= 3 and profit_ratio >= 0.7 and ocf_ratio >= 0.6 and clean_audit_ratio >= 0.8
    has_major_hole = len(red_flags) >= 2 or (profit_ratio >= 0.6 and ocf_ratio < 0.4)

    reasons: list[str] = []
    warnings: list[str] = []

    if total_years:
        reasons.append(f"Dữ liệu hoạt động theo năm: {total_years} năm")
    if integrity_ok:
        reasons.append("Doanh nghiệp có dấu hiệu làm ăn tương đối kỷ luật")
    else:
        warnings.append("Chất lượng kinh doanh chưa thật sự ổn định qua các năm")

    if has_major_hole:
        warnings.append("Phát hiện lỗ hổng báo cáo tài chính cần theo dõi thêm")
    if red_flags:
        warnings.append(f"Cờ đỏ nổi bật: {red_flags[0]}")

    if consecutive_dividend_years >= 3:
        reasons.append(f"Cổ tức tiền mặt trả đều {consecutive_dividend_years} năm liên tiếp")
    elif paid_years:
        reasons.append("Có chi trả cổ tức nhưng chưa đều qua các năm")
    else:
        warnings.append("Chưa có dữ liệu cổ tức tiền mặt ổn định")

    if avg_dividend > 0:
        reasons.append(f"Cổ tức tiền mặt bình quân 5 năm gần nhất: {avg_dividend:,.0f} ₫/cp")

    return {
        "business_years": total_years,
        "integrity_ok": integrity_ok,
        "has_major_hole": has_major_hole,
        "profit_consistency": round(profit_ratio, 4),
        "ocf_consistency": round(ocf_ratio, 4),
        "clean_audit_ratio": round(clean_audit_ratio, 4),
        "consecutive_dividend_years": consecutive_dividend_years,
        "avg_cash_dividend": round(avg_dividend, 2),
        "reasons": reasons,
        "warnings": warnings,
    }
