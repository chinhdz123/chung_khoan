import json
import logging
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AnnualDividend, AnnualFundamental, FinancialSnapshot, MarketSnapshot, NewsSnapshot
from app.services.data_provider import DataProvider


logger = logging.getLogger(__name__)


class DailyETLService:
    def __init__(self, provider: DataProvider | None = None) -> None:
        self.provider = provider or DataProvider()

    def run(
        self,
        db: Session,
        symbols: list[str],
        run_date: date,
        include_financial: bool = True,
        include_news: bool = True,
        skip_existing_today: bool = True,
    ) -> dict:
        symbols = sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()})
        details = {
            "run_date": run_date.isoformat(),
            "total_symbols": len(symbols),
            "include_financial": include_financial,
            "include_news": include_news,
            "skip_existing_today": skip_existing_today,
            "market_success": 0,
            "market_skipped": 0,
            "financial_success": 0,
            "financial_skipped": 0,
            "annual_success": 0,
            "annual_skipped": 0,
            "news_success": 0,
            "news_skipped": 0,
            "vnstock_quota_exhausted": False,
            "errors": [],
        }
        vnstock_quota_exhausted = False

        existing_market_symbols: set[str] = set()
        existing_financial_symbols: set[str] = set()
        existing_annual_symbols: set[str] = set()
        if skip_existing_today and symbols:
            existing_market_symbols = set(
                db.execute(
                    select(MarketSnapshot.symbol).where(
                        MarketSnapshot.snapshot_date == run_date,
                        MarketSnapshot.symbol.in_(symbols),
                    )
                ).scalars().all()
            )
            if include_financial:
                existing_financial_symbols = set(
                    db.execute(
                        select(FinancialSnapshot.symbol).where(
                            FinancialSnapshot.snapshot_date == run_date,
                            FinancialSnapshot.symbol.in_(symbols),
                        )
                    ).scalars().all()
                )
                existing_annual_symbols = set(
                    db.execute(select(AnnualFundamental.symbol).where(AnnualFundamental.symbol.in_(symbols))).scalars().all()
                )

        market_map: dict = {}
        if symbols:
            try:
                market_map = self.provider.fetch_market_bulk(symbols, run_date)
            except Exception as exc:
                logger.exception("bulk market ETL fetch failed")
                details["errors"].append(f"market_bulk:{exc}")

        for symbol in symbols:
            if skip_existing_today and symbol in existing_market_symbols:
                details["market_skipped"] += 1
                logger.info("market ETL skipped existing symbol=%s date=%s", symbol, run_date)
            else:
                try:
                    market_data = market_map.get(symbol) or self.provider.fetch_market(symbol, run_date)
                    self._upsert_market(db, market_data)
                    details["market_success"] += 1
                except Exception as exc:
                    logger.exception("market ETL failed for %s", symbol)
                    details["errors"].append(f"market:{symbol}:{exc}")

            if include_financial:
                if vnstock_quota_exhausted:
                    details["financial_skipped"] += 1
                    logger.info("financial ETL skipped by quota symbol=%s", symbol)
                elif skip_existing_today and symbol in existing_financial_symbols:
                    details["financial_skipped"] += 1
                    logger.info("financial ETL skipped existing symbol=%s date=%s", symbol, run_date)
                else:
                    try:
                        fin_data = self.provider.fetch_financial(symbol, run_date)
                        self._upsert_financial(db, fin_data)
                        details["financial_success"] += 1
                    except Exception as exc:
                        logger.warning("financial ETL skipped for %s: %s", symbol, exc)
                        details["errors"].append(f"financial:{symbol}:{exc}")
                        if self._is_rate_limit_error(exc):
                            vnstock_quota_exhausted = True
                            details["vnstock_quota_exhausted"] = True

                annual_already_present = symbol in existing_annual_symbols
                if vnstock_quota_exhausted:
                    details["annual_skipped"] += 1
                    logger.info("annual ETL skipped by quota symbol=%s", symbol)
                elif skip_existing_today and symbol in existing_financial_symbols and annual_already_present:
                    details["annual_skipped"] += 1
                    logger.info("annual ETL skipped existing symbol=%s", symbol)
                else:
                    try:
                        annual_fundamentals, annual_dividends = self.provider.fetch_annual_insights(symbol)
                        self._replace_annual_fundamentals(db, symbol, annual_fundamentals)
                        self._replace_annual_dividends(db, symbol, annual_dividends)
                        details["annual_success"] += 1
                    except Exception as exc:
                        logger.warning("annual ETL skipped for %s: %s", symbol, exc)
                        details["errors"].append(f"annual:{symbol}:{exc}")
                        if self._is_rate_limit_error(exc):
                            vnstock_quota_exhausted = True
                            details["vnstock_quota_exhausted"] = True

            if include_news:
                if vnstock_quota_exhausted:
                    details["news_skipped"] += 1
                    logger.info("news ETL skipped by quota symbol=%s", symbol)
                else:
                    try:
                        news_items = self.provider.fetch_news(symbol)
                        self._replace_news(db, symbol, news_items)
                        details["news_success"] += 1
                    except Exception as exc:
                        logger.warning("news ETL skipped for %s: %s", symbol, exc)
                        details["errors"].append(f"news:{symbol}:{exc}")
                        if self._is_rate_limit_error(exc):
                            vnstock_quota_exhausted = True
                            details["vnstock_quota_exhausted"] = True

        db.commit()
        logger.info("daily ETL done: %s", json.dumps(details, ensure_ascii=False))
        return details

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc).lower()
        keywords = ["rate limit", "quota", "429", "giới hạn", "gioi han", "too many requests"]
        return any(k in text for k in keywords)

    @staticmethod
    def _upsert_market(db: Session, market_data) -> None:
        def _same_price(a: float, b: float) -> bool:
            return abs(float(a or 0) - float(b or 0)) <= 0.001

        existing = db.execute(
            select(MarketSnapshot).where(
                MarketSnapshot.symbol == market_data.symbol,
                MarketSnapshot.snapshot_date == market_data.snapshot_date,
            )
        ).scalar_one_or_none()

        if existing:
            existing.open_price = market_data.open_price
            existing.high_price = market_data.high_price
            existing.low_price = market_data.low_price
            existing.close_price = market_data.close_price
            existing.volume = market_data.volume
            existing.foreign_net_value = market_data.foreign_net_value
            existing.proprietary_net_value = market_data.proprietary_net_value
            existing.retail_estimated_value = market_data.retail_estimated_value
        else:
            db.add(
                MarketSnapshot(
                    symbol=market_data.symbol,
                    snapshot_date=market_data.snapshot_date,
                    open_price=market_data.open_price,
                    high_price=market_data.high_price,
                    low_price=market_data.low_price,
                    close_price=market_data.close_price,
                    volume=market_data.volume,
                    foreign_net_value=market_data.foreign_net_value,
                    proprietary_net_value=market_data.proprietary_net_value,
                    retail_estimated_value=market_data.retail_estimated_value,
                )
            )

        # Clean up stale forward-dated placeholders (legacy behavior), where
        # same OHLC was copied to a newer date but flow fields remained zero.
        has_flow = float(market_data.foreign_net_value or 0) != 0 or float(market_data.proprietary_net_value or 0) != 0
        if not has_flow:
            return

        future_rows = db.execute(
            select(MarketSnapshot).where(
                MarketSnapshot.symbol == market_data.symbol,
                MarketSnapshot.snapshot_date > market_data.snapshot_date,
            )
        ).scalars().all()
        for row in future_rows:
            zero_flow = float(row.foreign_net_value or 0) == 0 and float(row.proprietary_net_value or 0) == 0
            same_ohlc = (
                _same_price(row.open_price, market_data.open_price)
                and _same_price(row.high_price, market_data.high_price)
                and _same_price(row.low_price, market_data.low_price)
                and _same_price(row.close_price, market_data.close_price)
            )
            if zero_flow and same_ohlc:
                logger.info(
                    "market ETL removed stale forward row symbol=%s stale_date=%s base_date=%s",
                    market_data.symbol,
                    row.snapshot_date,
                    market_data.snapshot_date,
                )
                db.delete(row)

    @staticmethod
    def _upsert_financial(db: Session, fin_data) -> None:
        existing = db.execute(
            select(FinancialSnapshot).where(
                FinancialSnapshot.symbol == fin_data.symbol,
                FinancialSnapshot.snapshot_date == fin_data.snapshot_date,
            )
        ).scalar_one_or_none()

        payload = {
            "pe": fin_data.pe,
            "pb": fin_data.pb,
            "roe": fin_data.roe,
            "roa": fin_data.roa,
            "debt_to_equity": fin_data.debt_to_equity,
            "current_ratio": fin_data.current_ratio,
            "operating_cash_flow": fin_data.operating_cash_flow,
            "free_cash_flow": fin_data.free_cash_flow,
            "revenue_growth": fin_data.revenue_growth,
            "profit_growth": fin_data.profit_growth,
            "eps": fin_data.eps,
            "auditor_opinion": fin_data.auditor_opinion,
            "red_flags_json": json.dumps(fin_data.red_flags, ensure_ascii=False),
        }

        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            return

        db.add(
            FinancialSnapshot(
                symbol=fin_data.symbol,
                snapshot_date=fin_data.snapshot_date,
                **payload,
            )
        )

    @staticmethod
    def _replace_news(db: Session, symbol: str, news_items) -> None:
        db.execute(delete(NewsSnapshot).where(NewsSnapshot.symbol == symbol))
        for item in news_items:
            db.add(
                NewsSnapshot(
                    symbol=item.symbol,
                    title=item.title,
                    url=item.url,
                    summary=item.summary,
                    sentiment=item.sentiment,
                    published_at=item.published_at,
                )
            )

    @staticmethod
    def _replace_annual_fundamentals(db: Session, symbol: str, rows) -> None:
        db.execute(delete(AnnualFundamental).where(AnnualFundamental.symbol == symbol))
        for row in rows:
            db.add(
                AnnualFundamental(
                    symbol=symbol,
                    fiscal_year=row.fiscal_year,
                    revenue=row.revenue,
                    net_profit=row.net_profit,
                    operating_cash_flow=row.operating_cash_flow,
                    free_cash_flow=row.free_cash_flow,
                    roe=row.roe,
                    debt_to_equity=row.debt_to_equity,
                    eps=row.eps,
                    auditor_opinion=row.auditor_opinion,
                    red_flags_json=json.dumps(row.red_flags, ensure_ascii=False),
                )
            )

    @staticmethod
    def _replace_annual_dividends(db: Session, symbol: str, rows) -> None:
        db.execute(delete(AnnualDividend).where(AnnualDividend.symbol == symbol))
        for row in rows:
            db.add(
                AnnualDividend(
                    symbol=symbol,
                    fiscal_year=row.fiscal_year,
                    cash_dividend_per_share=row.cash_dividend_per_share,
                    dividend_yield=row.dividend_yield,
                )
            )
