from sqlalchemy import delete

from app.database import SessionLocal
from app.models import (
    AdviceReport,
    AiUsageLog,
    Alert,
    FinancialSnapshot,
    MarketSnapshot,
    NewsSnapshot,
    PortfolioHealthSnapshot,
)
from app.schemas import HoldingsConfigInput, PositionInput, WatchlistConfigInput
from app.services.user_service import (
    ensure_default_user,
    get_holdings_config,
    get_watchlist_config,
    save_holdings_config,
    save_watchlist_config,
)


def main() -> None:
    db = SessionLocal()
    try:
        user = ensure_default_user(db)

        for model in [
            MarketSnapshot,
            FinancialSnapshot,
            NewsSnapshot,
            AdviceReport,
            Alert,
            PortfolioHealthSnapshot,
            AiUsageLog,
        ]:
            db.execute(delete(model))
        db.commit()

        watch_cfg = get_watchlist_config(db, user.id)
        watch_symbols = sorted(set([*watch_cfg.watchlist_symbols, "VEA", "HPG"]))
        save_watchlist_config(db, WatchlistConfigInput(watchlist_symbols=watch_symbols))

        hold_cfg = get_holdings_config(db, user.id)
        pos_map = {p.symbol.upper(): p for p in hold_cfg.positions}
        if "VEA" not in pos_map:
            pos_map["VEA"] = PositionInput(symbol="VEA", quantity=0, avg_cost=0)
        if "HPG" not in pos_map:
            pos_map["HPG"] = PositionInput(symbol="HPG", quantity=0, avg_cost=0)

        positions = [
            PositionInput(
                symbol=symbol,
                quantity=float(pos.quantity),
                avg_cost=float(pos.avg_cost),
                current_price=float(pos.current_price),
            )
            for symbol, pos in sorted(pos_map.items())
        ]

        save_holdings_config(
            db,
            HoldingsConfigInput(
                cash=float(hold_cfg.cash),
                positions=positions,
                symbol_rules=hold_cfg.symbol_rules,
                target_cash_ratio=float(hold_cfg.target_cash_ratio),
            ),
        )

        db.commit()
        print("UPDATED_WATCHLIST", watch_symbols)
        print("UPDATED_HOLDINGS", [(p.symbol, p.quantity, p.avg_cost) for p in positions])
        print("CLEARED_GENERATED_DATA", True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
