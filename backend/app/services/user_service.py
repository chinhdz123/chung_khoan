from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import CashBalance, MarketSnapshot, PortfolioPosition, SymbolRule, User, UserRule, WatchlistSymbol
from app.schemas import (
    HoldingsConfigInput,
    HoldingsConfigOutput,
    PortfolioTemplateInput,
    PortfolioTemplateOutput,
    PositionInput,
    SymbolRuleInput,
    WatchlistConfigInput,
    WatchlistConfigOutput,
)


def _normalize_stock_group_ratios(attack: float, balance: float, defense: float) -> tuple[float, float, float]:
    a = max(0.0, float(attack or 0))
    b = max(0.0, float(balance or 0))
    d = max(0.0, float(defense or 0))
    total = a + b + d
    if total <= 0:
        return 0.34, 0.33, 0.33
    return a / total, b / total, d / total


def ensure_default_user(db: Session, email: str = "local@user", full_name: str = "Local User") -> User:
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user:
        return user

    user = User(email=email, full_name=full_name, risk_profile="balanced")
    db.add(user)
    db.flush()

    db.add(CashBalance(user_id=user.id, cash=0))
    db.add(UserRule(user_id=user.id, disbursement_plan_json="[]"))
    db.commit()
    db.refresh(user)
    return user


def _latest_market_price(db: Session, symbol: str) -> float:
    price = db.execute(
        select(MarketSnapshot.close_price)
        .where(MarketSnapshot.symbol == symbol)
        .order_by(desc(MarketSnapshot.snapshot_date))
        .limit(1)
    ).scalar_one_or_none()
    return float(price or 0)


def save_template(db: Session, payload: PortfolioTemplateInput) -> PortfolioTemplateOutput:
    user = ensure_default_user(db)

    cash_row = db.execute(select(CashBalance).where(CashBalance.user_id == user.id)).scalar_one_or_none()
    if not cash_row:
        cash_row = CashBalance(user_id=user.id, cash=payload.cash)
        db.add(cash_row)
    else:
        cash_row.cash = payload.cash

    db.query(WatchlistSymbol).filter(WatchlistSymbol.user_id == user.id).delete()
    for symbol in sorted({s.strip().upper() for s in payload.watchlist_symbols if s.strip()}):
        db.add(WatchlistSymbol(user_id=user.id, symbol=symbol, is_active=True))

    db.query(PortfolioPosition).filter(PortfolioPosition.user_id == user.id).delete()
    for pos in payload.positions:
        symbol = pos.symbol.strip().upper()
        market_price = _latest_market_price(db, symbol)
        db.add(
            PortfolioPosition(
                user_id=user.id,
                symbol=symbol,
                quantity=pos.quantity,
                avg_cost=pos.avg_cost,
                current_price=market_price if market_price > 0 else float(pos.current_price or 0),
            )
        )

    db.query(SymbolRule).filter(SymbolRule.user_id == user.id).delete()
    for symbol_rule in payload.symbol_rules:
        db.add(
            SymbolRule(
                user_id=user.id,
                symbol=symbol_rule.symbol.strip().upper(),
                stop_accumulate_price=symbol_rule.stop_accumulate_price,
                take_profit_price=symbol_rule.take_profit_price,
            )
        )

    db.commit()
    return get_template(db, user.id)


def save_watchlist_config(db: Session, payload: WatchlistConfigInput) -> WatchlistConfigOutput:
    user = ensure_default_user(db)

    db.query(WatchlistSymbol).filter(WatchlistSymbol.user_id == user.id).delete()
    for symbol in sorted({s.strip().upper() for s in payload.watchlist_symbols if s.strip()}):
        db.add(WatchlistSymbol(user_id=user.id, symbol=symbol, is_active=True))

    db.commit()
    return get_watchlist_config(db, user.id)


def get_watchlist_config(db: Session, user_id: int) -> WatchlistConfigOutput:
    user = db.get(User, user_id)
    if not user:
        raise ValueError("User not found")

    watchlist = db.execute(select(WatchlistSymbol).where(WatchlistSymbol.user_id == user_id)).scalars().all()
    return WatchlistConfigOutput(
        user_id=user.id,
        watchlist_symbols=[w.symbol for w in watchlist],
        updated_at=datetime.utcnow(),
    )


def save_holdings_config(db: Session, payload: HoldingsConfigInput) -> HoldingsConfigOutput:
    user = ensure_default_user(db)

    rule_row = db.execute(select(UserRule).where(UserRule.user_id == user.id)).scalar_one_or_none()
    if not rule_row:
        rule_row = UserRule(user_id=user.id)
        db.add(rule_row)
    attack_ratio, balance_ratio, defense_ratio = _normalize_stock_group_ratios(
        payload.target_attack_stock_ratio,
        payload.target_balance_stock_ratio,
        payload.target_defense_stock_ratio,
    )
    rule_row.target_cash_ratio = float(payload.target_cash_ratio)
    rule_row.buy_zone_extra_margin = float(payload.buy_zone_extra_margin)
    rule_row.allocation_balance_tolerance = float(payload.allocation_balance_tolerance)
    rule_row.target_attack_stock_ratio = float(attack_ratio)
    rule_row.target_balance_stock_ratio = float(balance_ratio)
    rule_row.target_defense_stock_ratio = float(defense_ratio)

    cash_row = db.execute(select(CashBalance).where(CashBalance.user_id == user.id)).scalar_one_or_none()
    if not cash_row:
        cash_row = CashBalance(user_id=user.id, cash=payload.cash)
        db.add(cash_row)
    else:
        cash_row.cash = payload.cash

    db.query(PortfolioPosition).filter(PortfolioPosition.user_id == user.id).delete()
    for pos in payload.positions:
        symbol = pos.symbol.strip().upper()
        market_price = _latest_market_price(db, symbol)
        db.add(
            PortfolioPosition(
                user_id=user.id,
                symbol=symbol,
                quantity=pos.quantity,
                avg_cost=pos.avg_cost,
                current_price=market_price if market_price > 0 else float(pos.current_price or 0),
            )
        )

    db.query(SymbolRule).filter(SymbolRule.user_id == user.id).delete()
    for symbol_rule in payload.symbol_rules:
        db.add(
            SymbolRule(
                user_id=user.id,
                symbol=symbol_rule.symbol.strip().upper(),
                stop_accumulate_price=symbol_rule.stop_accumulate_price,
                take_profit_price=symbol_rule.take_profit_price,
            )
        )

    db.commit()
    return get_holdings_config(db, user.id)


def get_holdings_config(db: Session, user_id: int) -> HoldingsConfigOutput:
    user = db.get(User, user_id)
    if not user:
        raise ValueError("User not found")

    cash_row = db.execute(select(CashBalance).where(CashBalance.user_id == user_id)).scalar_one_or_none()
    positions = db.execute(select(PortfolioPosition).where(PortfolioPosition.user_id == user_id)).scalars().all()
    symbol_rules = db.execute(select(SymbolRule).where(SymbolRule.user_id == user_id)).scalars().all()
    rule_row = db.execute(select(UserRule).where(UserRule.user_id == user_id)).scalar_one_or_none()
    target_cash_ratio = float(rule_row.target_cash_ratio if rule_row else 0.5)
    buy_zone_extra_margin = float(rule_row.buy_zone_extra_margin if rule_row else 0.01)
    allocation_balance_tolerance = float(rule_row.allocation_balance_tolerance if rule_row else 0.02)
    target_attack_stock_ratio = float(rule_row.target_attack_stock_ratio if rule_row else 0.34)
    target_balance_stock_ratio = float(rule_row.target_balance_stock_ratio if rule_row else 0.33)
    target_defense_stock_ratio = float(rule_row.target_defense_stock_ratio if rule_row else 0.33)
    target_attack_stock_ratio, target_balance_stock_ratio, target_defense_stock_ratio = _normalize_stock_group_ratios(
        target_attack_stock_ratio,
        target_balance_stock_ratio,
        target_defense_stock_ratio,
    )
    position_inputs: list[PositionInput] = []
    for p in positions:
        market_price = _latest_market_price(db, p.symbol)
        position_inputs.append(
            PositionInput(
                symbol=p.symbol,
                quantity=float(p.quantity),
                avg_cost=float(p.avg_cost),
                current_price=market_price if market_price > 0 else float(p.current_price or 0),
            )
        )

    return HoldingsConfigOutput(
        user_id=user.id,
        cash=float(cash_row.cash if cash_row else 0),
        positions=position_inputs,
        symbol_rules=[
            SymbolRuleInput(
                symbol=sr.symbol,
                stop_accumulate_price=sr.stop_accumulate_price,
                take_profit_price=sr.take_profit_price,
            )
            for sr in symbol_rules
        ],
        target_cash_ratio=target_cash_ratio,
        target_stock_ratio=round(1 - target_cash_ratio, 4),
        buy_zone_extra_margin=buy_zone_extra_margin,
        allocation_balance_tolerance=allocation_balance_tolerance,
        target_attack_stock_ratio=round(target_attack_stock_ratio, 4),
        target_balance_stock_ratio=round(target_balance_stock_ratio, 4),
        target_defense_stock_ratio=round(target_defense_stock_ratio, 4),
        updated_at=datetime.utcnow(),
    )


def get_template(db: Session, user_id: int) -> PortfolioTemplateOutput:
    user = db.get(User, user_id)
    if not user:
        raise ValueError("User not found")

    cash_row = db.execute(select(CashBalance).where(CashBalance.user_id == user_id)).scalar_one_or_none()
    positions = db.execute(select(PortfolioPosition).where(PortfolioPosition.user_id == user_id)).scalars().all()
    watchlist = db.execute(select(WatchlistSymbol).where(WatchlistSymbol.user_id == user_id)).scalars().all()
    symbol_rules = db.execute(select(SymbolRule).where(SymbolRule.user_id == user_id)).scalars().all()
    position_inputs: list[PositionInput] = []
    for p in positions:
        market_price = _latest_market_price(db, p.symbol)
        position_inputs.append(
            PositionInput(
                symbol=p.symbol,
                quantity=float(p.quantity),
                avg_cost=float(p.avg_cost),
                current_price=market_price if market_price > 0 else float(p.current_price or 0),
            )
        )

    return PortfolioTemplateOutput(
        user_id=user.id,
        cash=float(cash_row.cash if cash_row else 0),
        watchlist_symbols=[w.symbol for w in watchlist],
        positions=position_inputs,
        symbol_rules=[
            SymbolRuleInput(
                symbol=sr.symbol,
                stop_accumulate_price=sr.stop_accumulate_price,
                take_profit_price=sr.take_profit_price,
            )
            for sr in symbol_rules
        ],
        updated_at=datetime.utcnow(),
    )
