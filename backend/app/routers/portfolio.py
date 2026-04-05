import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CashBalance, MarketSnapshot, PortfolioHealthSnapshot, PortfolioPosition, UserRule
from app.schemas import (
    AllocationOut,
    HealthOut,
    HoldingsConfigInput,
    HoldingsConfigOutput,
    PortfolioTemplateInput,
    PortfolioTemplateOutput,
    WatchlistConfigInput,
    WatchlistConfigOutput,
)
from app.services.user_service import (
    ensure_default_user,
    get_holdings_config,
    get_template,
    get_watchlist_config,
    save_holdings_config,
    save_template,
    save_watchlist_config,
)


router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])
PRICE_UNIT_VND = 1000


@router.get("/template", response_model=PortfolioTemplateOutput)
def get_portfolio_template(db: Session = Depends(get_db)):
    user = ensure_default_user(db)
    return get_template(db, user.id)


@router.put("/template", response_model=PortfolioTemplateOutput)
def update_portfolio_template(payload: PortfolioTemplateInput, db: Session = Depends(get_db)):
    return save_template(db, payload)


@router.get("/watchlist-config", response_model=WatchlistConfigOutput)
def get_watchlist_only_config(db: Session = Depends(get_db)):
    user = ensure_default_user(db)
    return get_watchlist_config(db, user.id)


@router.put("/watchlist-config", response_model=WatchlistConfigOutput)
def update_watchlist_only_config(payload: WatchlistConfigInput, db: Session = Depends(get_db)):
    return save_watchlist_config(db, payload)


@router.get("/holdings-config", response_model=HoldingsConfigOutput)
def get_holdings_only_config(db: Session = Depends(get_db)):
    user = ensure_default_user(db)
    return get_holdings_config(db, user.id)


@router.put("/holdings-config", response_model=HoldingsConfigOutput)
def update_holdings_only_config(payload: HoldingsConfigInput, db: Session = Depends(get_db)):
    return save_holdings_config(db, payload)


@router.get("/health", response_model=HealthOut)
def get_portfolio_health(db: Session = Depends(get_db)):
    user = ensure_default_user(db)
    row = db.execute(
        select(PortfolioHealthSnapshot)
        .where(PortfolioHealthSnapshot.user_id == user.id)
        .order_by(desc(PortfolioHealthSnapshot.snapshot_date))
        .limit(1)
    ).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Chưa có báo cáo rủi ro danh mục")

    return HealthOut(
        snapshot_date=row.snapshot_date,
        risk_score=row.risk_score,
        warnings=json.loads(row.warnings_json or "[]"),
        suggestions=json.loads(row.suggestions_json or "[]"),
    )


@router.get("/allocation", response_model=AllocationOut)
def get_portfolio_allocation(db: Session = Depends(get_db)):
    user = ensure_default_user(db)

    cash_row = db.execute(select(CashBalance).where(CashBalance.user_id == user.id)).scalar_one_or_none()
    cash = float(cash_row.cash if cash_row else 0)

    positions = db.execute(select(PortfolioPosition).where(PortfolioPosition.user_id == user.id)).scalars().all()
    stock_value = 0.0
    for p in positions:
        market_row = db.execute(
            select(MarketSnapshot)
            .where(MarketSnapshot.symbol == p.symbol)
            .order_by(desc(MarketSnapshot.snapshot_date))
            .limit(1)
        ).scalar_one_or_none()
        market_price = float(market_row.close_price) if market_row else 0.0
        cached_price = float(p.current_price or 0)
        latest_price = market_price if market_price > 0 else cached_price
        if latest_price > 0:
            stock_value += float(p.quantity) * latest_price * PRICE_UNIT_VND

    total_assets = cash + stock_value
    if total_assets <= 0:
        cash_ratio = 1.0
        stock_ratio = 0.0
    else:
        cash_ratio = cash / total_assets
        stock_ratio = stock_value / total_assets

    rule = db.execute(select(UserRule).where(UserRule.user_id == user.id)).scalar_one_or_none()
    target_cash_ratio = float(rule.target_cash_ratio if rule else 0.5)
    target_stock_ratio = 1 - target_cash_ratio

    return AllocationOut(
        cash=round(cash, 2),
        stock_value=round(stock_value, 2),
        total_assets=round(total_assets, 2),
        cash_ratio=round(cash_ratio, 4),
        stock_ratio=round(stock_ratio, 4),
        target_cash_ratio=round(target_cash_ratio, 4),
        target_stock_ratio=round(target_stock_ratio, 4),
        ratio_gap=round(stock_ratio - target_stock_ratio, 4),
    )
