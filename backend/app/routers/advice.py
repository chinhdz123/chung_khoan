import json
import logging
import re
from contextlib import contextmanager
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import AdviceReport, PortfolioHealthSnapshot, PortfolioPosition, WatchlistSymbol
from app.schemas import AdviceOut, JobRunResult, SymbolDecision
from app.services.advice_service import AdviceService
from app.services.data_provider import DataProvider
from app.services.etl import DailyETLService
from app.services.user_service import ensure_default_user
from app.utils import vn_today


router = APIRouter(prefix="/api", tags=["advice"])
logger = logging.getLogger(__name__)
settings = get_settings()
PRICE_UNIT_VND = 1000
BOARD_LOT_SIZE = 100

_job_lock = Lock()
_active_job_name = ""


@contextmanager
def _single_flight(job_name: str):
    global _active_job_name
    acquired = _job_lock.acquire(blocking=False)
    if not acquired:
        running = _active_job_name or "khác"
        raise HTTPException(status_code=429, detail=f"Đang chạy tác vụ {running}. Vui lòng đợi xong rồi thử lại.")

    _active_job_name = job_name
    try:
        yield
    finally:
        _active_job_name = ""
        _job_lock.release()


def _collect_symbols(db: Session) -> list[str]:
    watchlist = db.execute(select(WatchlistSymbol.symbol)).scalars().all()
    positions = db.execute(select(PortfolioPosition.symbol)).scalars().all()
    symbols = sorted({*(s.upper() for s in watchlist), *(s.upper() for s in positions)})
    if not symbols:
        symbols = ["VCB", "FPT", "HPG", "TCB", "VNM"]
    return symbols


def _collect_holding_symbols(db: Session) -> list[str]:
    user = ensure_default_user(db)
    positions = db.execute(select(PortfolioPosition.symbol).where(PortfolioPosition.user_id == user.id)).scalars().all()
    symbols = sorted({s.upper() for s in positions if s})
    if symbols:
        return symbols
    return _collect_symbols(db)


def _parse_symbols_param(symbols: str | None) -> list[str]:
    if not symbols:
        return []
    items = [s.strip().upper() for s in re.split(r"[\s,;]+", symbols) if s and s.strip()]
    return sorted(set(items))


def _normalize_legacy_decision(decision: SymbolDecision) -> SymbolDecision:
    legacy_reasons = {
        "Mốc giải ngân hệ thống kích hoạt",
        "Chưa chạm mốc giải ngân hệ thống",
        "Dùng mức giải ngân mặc định hệ thống",
    }
    decision.reasons = [r for r in decision.reasons if not any(x in r for x in legacy_reasons)]

    if decision.current_price < 1000 and decision.buy_zone > 1000:
        decision.buy_zone = round(decision.buy_zone / PRICE_UNIT_VND, 2)
    if decision.current_price < 1000 and decision.sell_zone > 1000:
        decision.sell_zone = round(decision.sell_zone / PRICE_UNIT_VND, 2)

    if decision.action == "BUY_ZONE" and decision.current_price > 0 and decision.final_disbursement_value > 0:
        raw_qty = decision.final_disbursement_value / (decision.current_price * PRICE_UNIT_VND)
        lot_qty = float(int(raw_qty // BOARD_LOT_SIZE) * BOARD_LOT_SIZE)
        decision.final_disbursement_quantity = lot_qty
        decision.final_disbursement_value = round(lot_qty * decision.current_price * PRICE_UNIT_VND, 2)
        if lot_qty <= 0 and not any("lô tối thiểu" in r for r in decision.reasons):
            decision.reasons.append(f"Tiền mặt chưa đủ mua lô tối thiểu {BOARD_LOT_SIZE} cp theo giá hiện tại")

    return decision


@router.get("/advice/latest", response_model=AdviceOut)
def latest_advice(db: Session = Depends(get_db)):
    user = ensure_default_user(db)
    report = db.execute(
        select(AdviceReport)
        .where(AdviceReport.user_id == user.id)
        .order_by(desc(AdviceReport.report_date))
        .limit(1)
    ).scalar_one_or_none()
    if not report:
        today = vn_today()
        return AdviceOut(
            report_date=today,
            summary="Chưa có báo cáo khuyến nghị. Hãy bấm 'Tạo khuyến nghị' sau khi cập nhật dữ liệu.",
            used_ai=False,
            ai_text=None,
            confidence=0,
            decisions=[],
            portfolio_risk_score=0,
            portfolio_warnings=[],
            portfolio_suggestions=[],
        )

    payload = json.loads(report.deterministic_payload_json)
    health_row = db.execute(
        select(PortfolioHealthSnapshot)
        .where(
            PortfolioHealthSnapshot.user_id == user.id,
            PortfolioHealthSnapshot.snapshot_date == report.report_date,
        )
    ).scalar_one_or_none()

    if health_row:
        warnings = json.loads(health_row.warnings_json or "[]")
        suggestions = json.loads(health_row.suggestions_json or "[]")
        risk_score = health_row.risk_score
    else:
        portfolio = payload.get("portfolio", {})
        warnings = portfolio.get("warnings", [])
        suggestions = portfolio.get("suggestions", [])
        risk_score = portfolio.get("risk_score", 0)

    decisions = [SymbolDecision(**d) for d in payload.get("decisions", [])]
    decisions = [_normalize_legacy_decision(d) for d in decisions]
    return AdviceOut(
        report_date=report.report_date,
        summary=report.summary,
        used_ai=report.used_ai,
        ai_text=report.ai_text,
        confidence=report.confidence,
        decisions=decisions,
        portfolio_risk_score=risk_score,
        portfolio_warnings=warnings,
        portfolio_suggestions=suggestions,
    )


@router.get("/advice/history")
def advice_history(limit: int = 30, db: Session = Depends(get_db)):
    user = ensure_default_user(db)
    rows = db.execute(
        select(AdviceReport)
        .where(AdviceReport.user_id == user.id)
        .order_by(desc(AdviceReport.report_date))
        .limit(limit)
    ).scalars().all()
    return [
        {
            "report_date": r.report_date,
            "summary": r.summary,
            "used_ai": r.used_ai,
            "confidence": r.confidence,
        }
        for r in rows
    ]


@router.post("/jobs/run-etl", response_model=JobRunResult)
def run_etl_now(
    force: bool = Query(default=False),
    symbols: str | None = Query(default=None, description="Danh sách mã, ngăn cách bởi dấu phẩy/khoảng trắng"),
    db: Session = Depends(get_db),
):
    run_date = vn_today()
    with _single_flight("run-etl"):
        used, wait_seconds = DataProvider.current_quota_state(settings.vnstock_max_requests_per_min)
        if force and wait_seconds > 0:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Đã chạm giới hạn VNSTOCK_MAX_REQUESTS_PER_MIN ({used}/{settings.vnstock_max_requests_per_min}). "
                    f"Vui lòng đợi khoảng {wait_seconds}s rồi thử lại."
                ),
            )

        service = DailyETLService()
        target_symbols = _parse_symbols_param(symbols) or _collect_symbols(db)
        try:
            result = service.run(
                db=db,
                symbols=target_symbols,
                run_date=run_date,
                include_financial=True,
                include_news=False,
                skip_existing_today=not force,
            )
            result["symbols"] = target_symbols
            market_success = int(result.get("market_success", 0) or 0)
            market_skipped = int(result.get("market_skipped", 0) or 0)
            errors = result.get("errors", []) or []
            ok = (market_success + market_skipped) > 0
            result["partial_success"] = len(errors) > 0
            return JobRunResult(ok=ok, run_date=run_date, details=result)
        except Exception as exc:
            logger.exception("run_etl_now_failed")
            return JobRunResult(
                ok=False,
                run_date=run_date,
                details={"run_date": run_date.isoformat(), "errors": [str(exc)]},
            )


@router.post("/jobs/run-etl-full", response_model=JobRunResult)
def run_etl_full_now(
    force: bool = Query(default=False),
    symbols: str | None = Query(default=None, description="Danh sách mã, ngăn cách bởi dấu phẩy/khoảng trắng"),
    db: Session = Depends(get_db),
):
    run_date = vn_today()
    with _single_flight("run-etl-full"):
        used, wait_seconds = DataProvider.current_quota_state(settings.vnstock_max_requests_per_min)
        if force and wait_seconds > 0:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Đã chạm giới hạn VNSTOCK_MAX_REQUESTS_PER_MIN ({used}/{settings.vnstock_max_requests_per_min}). "
                    f"Vui lòng đợi khoảng {wait_seconds}s rồi thử lại."
                ),
            )

        service = DailyETLService()
        target_symbols = _parse_symbols_param(symbols) or _collect_symbols(db)
        try:
            result = service.run(
                db=db,
                symbols=target_symbols,
                run_date=run_date,
                include_financial=True,
                include_news=True,
                skip_existing_today=not force,
            )
            result["symbols"] = target_symbols
            ok = len(result.get("errors", [])) == 0
            return JobRunResult(ok=ok, run_date=run_date, details=result)
        except Exception as exc:
            logger.exception("run_etl_full_now_failed")
            return JobRunResult(
                ok=False,
                run_date=run_date,
                details={"run_date": run_date.isoformat(), "errors": [str(exc)]},
            )


@router.post("/jobs/refresh-market", response_model=JobRunResult)
def refresh_market_only(
    force: bool = Query(default=False),
    symbols: str | None = Query(default=None, description="Danh sách mã, ngăn cách bởi dấu phẩy/khoảng trắng"),
    db: Session = Depends(get_db),
):
    run_date = vn_today()
    with _single_flight("refresh-market"):
        service = DailyETLService()
        target_symbols = _parse_symbols_param(symbols) or _collect_holding_symbols(db)
        try:
            result = service.run(
                db=db,
                symbols=target_symbols,
                run_date=run_date,
                include_financial=False,
                include_news=False,
                skip_existing_today=not force,
            )
            result["symbols"] = target_symbols
            ok = len(result.get("errors", [])) == 0
            return JobRunResult(ok=ok, run_date=run_date, details=result)
        except Exception as exc:
            logger.exception("refresh_market_only_failed")
            return JobRunResult(
                ok=False,
                run_date=run_date,
                details={"run_date": run_date.isoformat(), "errors": [str(exc)]},
            )


@router.post("/jobs/run-advice", response_model=JobRunResult)
def run_advice_now(db: Session = Depends(get_db)):
    with _single_flight("run-advice"):
        run_date = vn_today()
        user = ensure_default_user(db)
        service = AdviceService()
        report = service.run_for_user(db=db, user_id=user.id, run_date=run_date)
        db.commit()
        return JobRunResult(
            ok=True,
            run_date=run_date,
            details={
                "summary": report.summary,
                "used_ai": report.used_ai,
                "confidence": report.confidence,
            },
        )
