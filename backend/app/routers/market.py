import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnnualDividend, AnnualFundamental, FinancialSnapshot, MarketSnapshot, WatchlistSymbol
from app.services.data_provider import DataProvider
from app.services.rule_engine import assess_annual_quality
from app.services.user_service import ensure_default_user
from app.utils import vn_today


router = APIRouter(prefix="/api/market", tags=["market"])
logger = logging.getLogger(__name__)


@router.get("/symbols")
def symbols(db: Session = Depends(get_db)):
    user = ensure_default_user(db)
    watchlist = db.execute(
        select(WatchlistSymbol).where(WatchlistSymbol.user_id == user.id).order_by(WatchlistSymbol.symbol)
    ).scalars().all()
    return [w.symbol for w in watchlist]


@router.get("/{symbol}/snapshot")
def symbol_snapshot(symbol: str, db: Session = Depends(get_db)):
    symbol = symbol.upper()
    market_row = db.execute(
        select(MarketSnapshot)
        .where(MarketSnapshot.symbol == symbol)
        .order_by(desc(MarketSnapshot.snapshot_date))
        .limit(1)
    ).scalar_one_or_none()
    fin_row = db.execute(
        select(FinancialSnapshot)
        .where(FinancialSnapshot.symbol == symbol)
        .order_by(desc(FinancialSnapshot.snapshot_date))
        .limit(1)
    ).scalar_one_or_none()
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
    annual_quality = assess_annual_quality(annual_fundamentals, annual_dividends)

    if not market_row:
        raise HTTPException(status_code=404, detail=f"No market snapshot for {symbol}")

    return {
        "symbol": symbol,
        "market": {
            "snapshot_date": market_row.snapshot_date,
            "open_price": market_row.open_price,
            "high_price": market_row.high_price,
            "low_price": market_row.low_price,
            "close_price": market_row.close_price,
            "volume": market_row.volume,
            "foreign_net_value": market_row.foreign_net_value,
            "proprietary_net_value": market_row.proprietary_net_value,
            "retail_estimated_value": market_row.retail_estimated_value,
        },
        "financial": (
            {
                "snapshot_date": fin_row.snapshot_date,
                "pe": fin_row.pe,
                "pb": fin_row.pb,
                "roe": fin_row.roe,
                "debt_to_equity": fin_row.debt_to_equity,
                "current_ratio": fin_row.current_ratio,
                "operating_cash_flow": fin_row.operating_cash_flow,
                "free_cash_flow": fin_row.free_cash_flow,
                "auditor_opinion": fin_row.auditor_opinion,
            }
            if fin_row
            else None
        ),
        "annual_quality": annual_quality,
    }


@router.get("/{symbol}/history")
def symbol_history(
    symbol: str,
    days: int = Query(default=5, ge=1, le=60),
    db: Session = Depends(get_db),
):
    symbol = symbol.upper()
    rows = db.execute(
        select(MarketSnapshot)
        .where(MarketSnapshot.symbol == symbol)
        .order_by(desc(MarketSnapshot.snapshot_date))
        .limit(days)
    ).scalars().all()

    if len(rows) < days:
        try:
            provider = DataProvider()
            remote_rows = provider.fetch_market_history(symbol=symbol, end_date=vn_today(), days=days)
            if remote_rows:
                return [
                    {
                        "snapshot_date": row.snapshot_date,
                        "open_price": row.open_price,
                        "high_price": row.high_price,
                        "low_price": row.low_price,
                        "close_price": row.close_price,
                        "volume": row.volume,
                        "foreign_net_value": row.foreign_net_value,
                        "proprietary_net_value": row.proprietary_net_value,
                        "retail_estimated_value": row.retail_estimated_value,
                    }
                    for row in remote_rows
                ]
        except Exception as exc:
            logger.warning("symbol_history_remote_fetch_failed symbol=%s days=%s error=%s", symbol, days, exc)

    return [
        {
            "snapshot_date": row.snapshot_date,
            "open_price": row.open_price,
            "high_price": row.high_price,
            "low_price": row.low_price,
            "close_price": row.close_price,
            "volume": row.volume,
            "foreign_net_value": row.foreign_net_value,
            "proprietary_net_value": row.proprietary_net_value,
            "retail_estimated_value": row.retail_estimated_value,
        }
        for row in rows
    ]


@router.get("/watchlist-snapshots")
def watchlist_snapshots(db: Session = Depends(get_db)):
    user = ensure_default_user(db)
    watchlist_symbols = db.execute(
        select(WatchlistSymbol.symbol).where(WatchlistSymbol.user_id == user.id).order_by(WatchlistSymbol.symbol)
    ).scalars().all()

    data: list[dict] = []
    for symbol in watchlist_symbols:
        market_row = db.execute(
            select(MarketSnapshot)
            .where(MarketSnapshot.symbol == symbol)
            .order_by(desc(MarketSnapshot.snapshot_date))
            .limit(1)
        ).scalar_one_or_none()

        fin_row = db.execute(
            select(FinancialSnapshot)
            .where(FinancialSnapshot.symbol == symbol)
            .order_by(desc(FinancialSnapshot.snapshot_date))
            .limit(1)
        ).scalar_one_or_none()

        data.append(
            {
                "symbol": symbol,
                "market": (
                    {
                        "snapshot_date": market_row.snapshot_date,
                        "close_price": market_row.close_price,
                        "volume": market_row.volume,
                        "foreign_net_value": market_row.foreign_net_value,
                        "proprietary_net_value": market_row.proprietary_net_value,
                    }
                    if market_row
                    else None
                ),
                "financial": (
                    {
                        "pe": fin_row.pe,
                        "pb": fin_row.pb,
                        "roe": fin_row.roe,
                        "debt_to_equity": fin_row.debt_to_equity,
                    }
                    if fin_row
                    else None
                ),
            }
        )

    return data
