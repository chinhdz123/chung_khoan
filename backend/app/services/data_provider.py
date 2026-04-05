import logging
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from app.config import get_settings


logger = logging.getLogger(__name__)


@dataclass
class MarketData:
    symbol: str
    snapshot_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    foreign_net_value: float
    proprietary_net_value: float
    retail_estimated_value: float


@dataclass
class FinancialData:
    symbol: str
    snapshot_date: date
    pe: float
    pb: float
    roe: float
    roa: float
    debt_to_equity: float
    current_ratio: float
    operating_cash_flow: float
    free_cash_flow: float
    revenue_growth: float
    profit_growth: float
    eps: float
    auditor_opinion: str
    red_flags: list[str]


@dataclass
class NewsItem:
    symbol: str
    title: str
    url: str | None
    summary: str
    sentiment: str
    published_at: datetime


@dataclass
class AnnualFundamentalData:
    symbol: str
    fiscal_year: int
    revenue: float | None
    net_profit: float | None
    operating_cash_flow: float | None
    free_cash_flow: float | None
    roe: float | None
    debt_to_equity: float | None
    eps: float | None
    auditor_opinion: str | None
    red_flags: list[str]


@dataclass
class AnnualDividendData:
    symbol: str
    fiscal_year: int
    cash_dividend_per_share: float | None
    dividend_yield: float | None


class DataProvider:
    _global_request_timestamps: deque[float] = deque()
    _global_throttle_lock = Lock()

    def __init__(self) -> None:
        self.settings = get_settings()
        self._max_requests_per_min = max(1, int(self.settings.vnstock_max_requests_per_min))
        self._retry_attempts = max(1, int(self.settings.vnstock_retry_attempts))
        self._eod_max_back_days = max(0, int(self.settings.eod_market_max_back_days))
        self._market_cache: dict[tuple[str, str], MarketData] = {}
        self._vnstock_ready = self._detect_vnstock()
        if self._vnstock_ready:
            self._register_vnstock_user()

    @staticmethod
    def _detect_vnstock() -> bool:
        try:
            __import__("vnstock")
            return True
        except Exception:
            logger.error("vnstock not available; fake fallback is disabled")
            return False

    def fetch_market(self, symbol: str, snapshot_date: date) -> MarketData:
        symbol = symbol.strip().upper()
        market_by_symbol = self.fetch_market_bulk([symbol], snapshot_date)
        row = market_by_symbol.get(symbol)
        if row is None:
            raise RuntimeError(f"No market EOD data for {symbol}")
        return row

    def fetch_market_history(self, symbol: str, end_date: date, days: int) -> list[MarketData]:
        symbol = symbol.strip().upper()
        if not symbol or days <= 0:
            return []

        lookback_days = max(30, int(days) * 4)
        start_date = end_date - timedelta(days=lookback_days)
        rows = self._request_eod_rows_range(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            size=max(200, int(days) * 6),
        )
        if not rows:
            return []

        market_by_date: dict[date, MarketData] = {}
        for row in rows:
            code = str(row.get("code", "")).strip().upper()
            if code != symbol:
                continue
            market = self._market_data_from_eod_row(symbol, row)
            market_by_date[market.snapshot_date] = market

        if not market_by_date:
            return []

        foreign_series = self._fetch_foreign_flow_series(symbol, start_date, end_date)
        prop_series = self._fetch_proprietary_flow_series(symbol, start_date, end_date)
        for snap_date, market in market_by_date.items():
            if snap_date in foreign_series:
                market.foreign_net_value = foreign_series[snap_date]
            if snap_date in prop_series:
                market.proprietary_net_value = prop_series[snap_date]
            traded_value = market.retail_estimated_value
            market.retail_estimated_value = max(0.0, traded_value - market.foreign_net_value - market.proprietary_net_value)

        sorted_rows = sorted(market_by_date.values(), key=lambda x: x.snapshot_date, reverse=True)
        return sorted_rows[:days]

    def fetch_market_bulk(self, symbols: list[str], snapshot_date: date) -> dict[str, MarketData]:
        clean_symbols = sorted({s.strip().upper() for s in symbols if s and s.strip()})
        if not clean_symbols:
            return {}

        cache_key_prefix = snapshot_date.isoformat()
        missing = [s for s in clean_symbols if (cache_key_prefix, s) not in self._market_cache]
        if missing:
            fetched = self._call_with_retry(
                lambda: self._fetch_market_bulk_eod(missing, snapshot_date),
                op_name="fetch_market_bulk",
                symbol=",".join(missing[:5]),
            )
            for symbol, market_data in fetched.items():
                self._market_cache[(cache_key_prefix, symbol)] = market_data

        return {
            symbol: self._market_cache[(cache_key_prefix, symbol)]
            for symbol in clean_symbols
            if (cache_key_prefix, symbol) in self._market_cache
        }

    def fetch_financial(self, symbol: str, snapshot_date: date) -> FinancialData:
        if not self._vnstock_ready:
            raise RuntimeError("vnstock unavailable; cannot fetch financial data")
        return self._call_with_retry(
            lambda: self._fetch_financial_vnstock(symbol, snapshot_date),
            op_name="fetch_financial",
            symbol=symbol,
        )

    def fetch_news(self, symbol: str, limit: int = 3) -> list[NewsItem]:
        if not self._vnstock_ready:
            raise RuntimeError("vnstock unavailable; cannot fetch news data")
        return self._call_with_retry(
            lambda: self._fetch_news_vnstock(symbol, limit),
            op_name="fetch_news",
            symbol=symbol,
        )

    def fetch_annual_insights(self, symbol: str) -> tuple[list[AnnualFundamentalData], list[AnnualDividendData]]:
        if not self._vnstock_ready:
            return [], []
        return self._call_with_retry(
            lambda: self._fetch_annual_insights_vnstock(symbol),
            op_name="fetch_annual_insights",
            symbol=symbol,
        )

    def _fetch_market_bulk_eod(self, symbols: list[str], snapshot_date: date) -> dict[str, MarketData]:
        remaining = set(symbols)
        collected: dict[str, MarketData] = {}

        for delta_days in range(self._eod_max_back_days + 1):
            if not remaining:
                break

            target_date = snapshot_date - timedelta(days=delta_days)
            rows = self._request_eod_rows(sorted(remaining), target_date)
            for row in rows:
                symbol = str(row.get("code", "")).strip().upper()
                if symbol not in remaining:
                    continue
                collected[symbol] = self._market_data_from_eod_row(symbol, row)
                remaining.remove(symbol)

        self._enrich_market_flows_from_vndirect(collected)

        if (
            self._vnstock_ready
            and self.settings.vnstock_enrich_market_flows
            and (self.settings.vnstock_api_key or "").strip()
            and collected
        ):
            for symbol, market_data in collected.items():
                if market_data.foreign_net_value != 0 and market_data.proprietary_net_value != 0:
                    continue
                try:
                    foreign_net, proprietary_net = self._call_with_retry(
                        lambda s=symbol: self._fetch_market_flows_vnstock(s),
                        op_name="fetch_market_flows",
                        symbol=symbol,
                    )
                    traded_value = (
                        market_data.retail_estimated_value
                        + market_data.foreign_net_value
                        + market_data.proprietary_net_value
                    )
                    if market_data.foreign_net_value == 0:
                        market_data.foreign_net_value = foreign_net
                    if market_data.proprietary_net_value == 0:
                        market_data.proprietary_net_value = proprietary_net
                    market_data.retail_estimated_value = max(
                        0.0,
                        traded_value - market_data.foreign_net_value - market_data.proprietary_net_value,
                    )
                except Exception:
                    logger.warning("market_flow_enrich_failed symbol=%s", symbol)

        return collected

    def _enrich_market_flows_from_vndirect(self, collected: dict[str, MarketData]) -> None:
        if not collected:
            return

        by_date: dict[str, list[str]] = {}
        for symbol, market_data in collected.items():
            date_key = market_data.snapshot_date.isoformat()
            by_date.setdefault(date_key, []).append(symbol)

        for date_key, symbols in by_date.items():
            try:
                target_date = date.fromisoformat(date_key)
                foreign_map = self._fetch_foreign_flow_map(symbols, target_date)
                prop_map = self._fetch_proprietary_flow_map(symbols, target_date)
                for symbol in symbols:
                    market_data = collected.get(symbol)
                    if not market_data:
                        continue
                    if symbol in foreign_map:
                        market_data.foreign_net_value = foreign_map[symbol]
                    if symbol in prop_map:
                        market_data.proprietary_net_value = prop_map[symbol]

                    traded_value = market_data.retail_estimated_value
                    market_data.retail_estimated_value = max(
                        0.0,
                        traded_value - market_data.foreign_net_value - market_data.proprietary_net_value,
                    )
            except Exception as exc:
                logger.warning("vndirect_flow_enrich_failed date=%s symbols=%s error=%s", date_key, symbols[:5], exc)

    def _fetch_foreign_flow_map(self, symbols: list[str], target_date: date) -> dict[str, float]:
        query = {
            "q": f"code:{','.join(symbols)}~tradingDate:{target_date.isoformat()}",
            "size": str(max(100, len(symbols) * 2)),
            "page": "1",
        }
        rows = self._request_json_rows(self.settings.eod_foreign_api_url, query)
        result: dict[str, float] = {}
        for row in rows:
            code = str(row.get("code", "")).strip().upper()
            if not code:
                continue
            net_val = row.get("netVal", 0)
            try:
                result[code] = self._parse_number(net_val)
            except Exception:
                continue
        return result

    def _fetch_proprietary_flow_map(self, symbols: list[str], target_date: date) -> dict[str, float]:
        query = {
            "q": f"code:{','.join(symbols)}~date:{target_date.isoformat()}",
            "size": str(max(100, len(symbols) * 2)),
            "page": "1",
        }
        rows = self._request_json_rows(self.settings.eod_proprietary_api_url, query)
        result: dict[str, float] = {}
        for row in rows:
            code = str(row.get("code", "")).strip().upper()
            if not code:
                continue
            net_val = row.get("netVal", 0)
            try:
                result[code] = self._parse_number(net_val)
            except Exception:
                continue
        return result

    def _request_json_rows(self, base_url: str, query: dict[str, str]) -> list[dict]:
        url = f"{base_url}?{urlencode(query)}"
        req = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "kyluat-dautu/1.0",
            },
        )
        with urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return data if isinstance(data, list) else []

    def _request_eod_rows(self, symbols: list[str], snapshot_date: date) -> list[dict]:
        if not symbols:
            return []

        query = {
            "q": f"code:{','.join(symbols)}~date:{snapshot_date.isoformat()}",
            "size": str(max(100, len(symbols))),
            "page": "1",
        }
        url = f"{self.settings.eod_market_api_url}?{urlencode(query)}"
        req = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "kyluat-dautu/1.0",
            },
        )

        with urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return data if isinstance(data, list) else []

    def _request_eod_rows_range(self, symbol: str, start_date: date, end_date: date, size: int = 500) -> list[dict]:
        query = {
            "q": f"code:{symbol}~date:gte:{start_date.isoformat()}~date:lte:{end_date.isoformat()}",
            "size": str(max(100, size)),
            "page": "1",
        }
        return self._request_json_rows(self.settings.eod_market_api_url, query)

    def _fetch_foreign_flow_series(self, symbol: str, start_date: date, end_date: date) -> dict[date, float]:
        query = {
            "q": f"code:{symbol}~tradingDate:gte:{start_date.isoformat()}~tradingDate:lte:{end_date.isoformat()}",
            "size": "500",
            "page": "1",
        }
        rows = self._request_json_rows(self.settings.eod_foreign_api_url, query)
        result: dict[date, float] = {}
        for row in rows:
            date_str = str(row.get("tradingDate", "")).strip()
            if not date_str:
                continue
            try:
                d = date.fromisoformat(date_str)
                result[d] = self._parse_number(row.get("netVal", 0))
            except Exception:
                continue
        return result

    def _fetch_proprietary_flow_series(self, symbol: str, start_date: date, end_date: date) -> dict[date, float]:
        query = {
            "q": f"code:{symbol}~date:gte:{start_date.isoformat()}~date:lte:{end_date.isoformat()}",
            "size": "500",
            "page": "1",
        }
        rows = self._request_json_rows(self.settings.eod_proprietary_api_url, query)
        result: dict[date, float] = {}
        for row in rows:
            date_str = str(row.get("date", "")).strip()
            if not date_str:
                continue
            try:
                d = date.fromisoformat(date_str)
                result[d] = self._parse_number(row.get("netVal", 0))
            except Exception:
                continue
        return result

    @staticmethod
    def _market_data_from_eod_row(symbol: str, row: dict) -> MarketData:
        row_date = str(row.get("date", "")).strip()
        try:
            snapshot_date = date.fromisoformat(row_date)
        except Exception:
            snapshot_date = date.today()

        close_price = float(row.get("close") or row.get("adClose") or 0)
        open_price = float(row.get("open") or row.get("adOpen") or close_price)
        high_price = float(row.get("high") or row.get("adHigh") or close_price)
        low_price = float(row.get("low") or row.get("adLow") or close_price)
        volume = float(row.get("nmVolume") or row.get("volume") or 0)
        traded_value = float(row.get("nmValue") or (close_price * volume * 1000) or 0)

        return MarketData(
            symbol=symbol,
            snapshot_date=snapshot_date,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=volume,
            foreign_net_value=0.0,
            proprietary_net_value=0.0,
            retail_estimated_value=traded_value,
        )

    def _fetch_market_vnstock(self, symbol: str, snapshot_date: date) -> MarketData:
        from vnstock import Vnstock

        stock = Vnstock().stock(symbol=symbol, source="VCI")
        start_date = (snapshot_date - timedelta(days=15)).isoformat()
        end_date = snapshot_date.isoformat()
        quote_df = stock.quote.history(start=start_date, end=end_date, interval="1D")
        if quote_df is None or len(quote_df) == 0:
            raise RuntimeError(f"No quote history for {symbol}")

        row = quote_df.sort_values("time").iloc[-1]
        foreign_net = 0.0
        prop_net = 0.0
        traded_value = float(row.get("close", 0) or 0) * float(row.get("volume", 0) or 0) * 1000
        retail_est = traded_value - foreign_net - prop_net

        return MarketData(
            symbol=symbol,
            snapshot_date=snapshot_date,
            open_price=float(row.get("open", row.get("open_price", 0))),
            high_price=float(row.get("high", row.get("high_price", 0))),
            low_price=float(row.get("low", row.get("low_price", 0))),
            close_price=float(row.get("close", row.get("close_price", 0))),
            volume=float(row.get("volume", 0)),
            foreign_net_value=foreign_net,
            proprietary_net_value=prop_net,
            retail_estimated_value=retail_est,
        )

    def _fetch_market_flows_vnstock(self, symbol: str) -> tuple[float, float]:
        from vnstock import Vnstock

        stock = Vnstock().stock(symbol=symbol, source="VCI")
        price_board = stock.trading.price_board([symbol])
        board_row = self._flatten_columns(price_board).iloc[0] if price_board is not None and len(price_board) else {}

        normalized_values = self._normalized_numeric_map(board_row)

        foreign_buy = self._find_value_by_aliases(
            normalized_values,
            [
                "foreign_buy_value",
                "foreignBuyValue",
                "foreign_buy",
                "foreignbuyvalue",
                "foreignbuy",
            ],
        )
        foreign_sell = self._find_value_by_aliases(
            normalized_values,
            [
                "foreign_sell_value",
                "foreignSellValue",
                "foreign_sell",
                "foreignsellvalue",
                "foreignsell",
            ],
        )
        foreign_net = self._find_value_by_aliases(
            normalized_values,
            [
                "foreign_net_value",
                "foreignNetValue",
                "foreign_net",
                "foreignnetvalue",
                "foreignnet",
            ],
        )

        proprietary_buy = self._find_value_by_aliases(
            normalized_values,
            [
                "proprietary_buy_value",
                "proprietaryBuyValue",
                "prop_buy_value",
                "propbuyvalue",
                "proprietarybuy",
                "self_trading_buy_value",
                "selftradingbuyvalue",
            ],
        )
        proprietary_sell = self._find_value_by_aliases(
            normalized_values,
            [
                "proprietary_sell_value",
                "proprietarySellValue",
                "prop_sell_value",
                "propsellvalue",
                "proprietarysell",
                "self_trading_sell_value",
                "selftradingsellvalue",
            ],
        )
        proprietary_net = self._find_value_by_aliases(
            normalized_values,
            [
                "proprietary_net_value",
                "proprietaryNetValue",
                "proprietary_net",
                "prop_net_value",
                "propNetValue",
                "prop_net",
                "self_trading_net_value",
                "selftradingnetvalue",
            ],
        )

        if proprietary_net == 0:
            proprietary_net = self._find_value_by_tokens(
                normalized_values,
                include_groups=[("proprietary", "net"), ("self", "trading", "net"), ("prop", "net"), ("tudoanh", "rong")],
            )

        foreign_net_value = (foreign_buy - foreign_sell) if (foreign_buy or foreign_sell) else foreign_net
        if proprietary_buy or proprietary_sell:
            proprietary_net_value = proprietary_buy - proprietary_sell
        else:
            proprietary_net_value = proprietary_net

        if proprietary_net_value == 0:
            candidate_keys = [k for k in normalized_values if ("prop" in k or "proprietary" in k or "selftrading" in k or "tudoanh" in k)]
            if candidate_keys:
                logger.info(
                    "proprietary_flow_zero symbol=%s keys=%s",
                    symbol,
                    candidate_keys[:8],
                )

        return foreign_net_value, proprietary_net_value

    def _fetch_annual_insights_vnstock(self, symbol: str) -> tuple[list[AnnualFundamentalData], list[AnnualDividendData]]:
        from vnstock import Vnstock

        stock = Vnstock().stock(symbol=symbol, source="VCI")

        ratio_df = self._call_dataframe_method(getattr(getattr(stock, "finance", None), "ratio", None), period="year")
        income_df = self._call_dataframe_method(
            getattr(getattr(stock, "finance", None), "income_statement", None),
            period="year",
        )
        cf_df = self._call_dataframe_method(getattr(getattr(stock, "finance", None), "cash_flow", None), period="year")

        div_df = self._call_dataframe_method(getattr(getattr(stock, "finance", None), "dividend", None))
        if div_df is None or len(div_df) == 0:
            div_df = self._call_dataframe_method(getattr(getattr(stock, "company", None), "dividends", None))
        if div_df is None or len(div_df) == 0:
            div_df = self._call_dataframe_method(getattr(getattr(stock, "company", None), "dividend", None))

        ratio_by_year = self._rows_by_year(ratio_df)
        income_by_year = self._rows_by_year(income_df)
        cf_by_year = self._rows_by_year(cf_df)
        div_by_year = self._rows_by_year(div_df)

        all_years = sorted({*ratio_by_year.keys(), *income_by_year.keys(), *cf_by_year.keys()}, reverse=True)
        fundamentals: list[AnnualFundamentalData] = []
        for year in all_years[:12]:
            ratio_row = ratio_by_year.get(year)
            income_row = income_by_year.get(year)
            cf_row = cf_by_year.get(year)

            revenue = self._pick_numeric_from_rows(
                [income_row],
                include_tokens=[("revenue",), ("doanh", "thu")],
                exclude_tokens=[("growth",)],
            )
            net_profit = self._pick_numeric_from_rows(
                [income_row],
                include_tokens=[("profit", "after", "tax"), ("net", "income"), ("lnst",)],
            )
            operating_cf = self._pick_numeric_from_rows(
                [cf_row],
                include_tokens=[("operating", "cash", "flow"), ("hoat", "dong", "kinh", "doanh")],
            )
            investing_cf = self._pick_numeric_from_rows(
                [cf_row],
                include_tokens=[("investing", "cash", "flow"), ("hoat", "dong", "dau", "tu")],
            )
            free_cf = None
            if operating_cf is not None and investing_cf is not None:
                free_cf = operating_cf + investing_cf
            elif operating_cf is not None:
                free_cf = operating_cf

            roe = self._pick_numeric_from_rows([ratio_row], include_tokens=[("roe",)])
            if roe is not None and roe <= 1:
                roe *= 100
            debt_to_equity = self._pick_numeric_from_rows(
                [ratio_row],
                include_tokens=[("debt", "equity"), ("d", "e")],
                exclude_tokens=[("long",)],
            )
            eps = self._pick_numeric_from_rows([ratio_row], include_tokens=[("eps",)])

            auditor_opinion = self._pick_text_from_rows(
                [income_row, ratio_row],
                include_tokens=[("auditor",), ("audit",), ("kiem", "toan")],
            )

            red_flags: list[str] = []
            if debt_to_equity is not None and debt_to_equity > 2.5:
                red_flags.append("Đòn bẩy nợ cao")
            if operating_cf is not None and net_profit is not None and net_profit > 0 and operating_cf < 0:
                red_flags.append("Lợi nhuận dương nhưng dòng tiền kinh doanh âm")
            if roe is not None and roe < 5:
                red_flags.append("ROE thấp")

            fundamentals.append(
                AnnualFundamentalData(
                    symbol=symbol,
                    fiscal_year=year,
                    revenue=revenue,
                    net_profit=net_profit,
                    operating_cash_flow=operating_cf,
                    free_cash_flow=free_cf,
                    roe=roe,
                    debt_to_equity=debt_to_equity,
                    eps=eps,
                    auditor_opinion=auditor_opinion,
                    red_flags=red_flags,
                )
            )

        dividends: list[AnnualDividendData] = []
        for year in sorted(div_by_year.keys(), reverse=True)[:15]:
            div_row = div_by_year.get(year)
            cash_div = self._pick_numeric_from_rows(
                [div_row],
                include_tokens=[("cash", "dividend"), ("co", "tuc", "tien", "mat")],
            )
            dividend_yield = self._pick_numeric_from_rows(
                [div_row],
                include_tokens=[("dividend", "yield"), ("ty", "suat", "co", "tuc")],
            )
            if cash_div is None and dividend_yield is None:
                continue
            dividends.append(
                AnnualDividendData(
                    symbol=symbol,
                    fiscal_year=year,
                    cash_dividend_per_share=cash_div,
                    dividend_yield=dividend_yield,
                )
            )

        return fundamentals, dividends

    @staticmethod
    def _normalized_numeric_map(row) -> dict[str, float]:
        if row is None:
            return {}
        if hasattr(row, "to_dict"):
            raw = row.to_dict()
        elif isinstance(row, dict):
            raw = row
        else:
            raw = {}

        result: dict[str, float] = {}
        for key, value in raw.items():
            norm_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
            if not norm_key:
                continue
            try:
                num = DataProvider._parse_number(value)
            except Exception:
                continue
            result[norm_key] = num
        return result

    @staticmethod
    def _parse_number(value) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            raise ValueError("empty")
        negative = text.startswith("(") and text.endswith(")")
        text = text.strip("()")
        text = text.replace(" ", "")
        text = text.replace(",", "")
        num = float(text)
        return -num if negative else num

    def _call_dataframe_method(self, method, **kwargs) -> pd.DataFrame:
        if not callable(method):
            return pd.DataFrame()
        try:
            data = method(**kwargs)
        except TypeError:
            try:
                data = method()
            except Exception:
                return pd.DataFrame()
        except Exception:
            return pd.DataFrame()
        return self._flatten_columns(data)

    def _rows_by_year(self, df: pd.DataFrame | None) -> dict[int, dict]:
        if df is None or len(df) == 0:
            return {}
        normalized = self._flatten_columns(df)
        result: dict[int, dict] = {}
        for _, row in normalized.iterrows():
            row_dict = row.to_dict() if hasattr(row, "to_dict") else {}
            year = self._extract_fiscal_year(row_dict)
            if year is None:
                continue
            if year not in result:
                result[year] = row_dict
        return result

    @staticmethod
    def _extract_fiscal_year(row_dict: dict) -> int | None:
        if not row_dict:
            return None
        for key, value in row_dict.items():
            key_norm = re.sub(r"[^a-z0-9]+", "", str(key).lower())
            if key_norm not in {
                "year",
                "fiscalyear",
                "reportyear",
                "period",
                "nam",
                "namtaichinh",
                "date",
                "reportdate",
            }:
                continue
            matched = re.search(r"(19|20)\d{2}", str(value))
            if matched:
                return int(matched.group(0))
        for value in row_dict.values():
            matched = re.search(r"(19|20)\d{2}", str(value))
            if matched:
                return int(matched.group(0))
        return None

    @staticmethod
    def _pick_numeric_from_rows(
        rows: list[dict | None],
        include_tokens: list[tuple[str, ...]],
        exclude_tokens: list[tuple[str, ...]] | None = None,
    ) -> float | None:
        exclude_tokens = exclude_tokens or []
        for row in rows:
            if not row:
                continue
            for key, value in row.items():
                key_norm = re.sub(r"[^a-z0-9]+", "", str(key).lower())
                if not key_norm:
                    continue
                matched_include = any(all(token in key_norm for token in tokens) for tokens in include_tokens)
                if not matched_include:
                    continue
                matched_exclude = any(all(token in key_norm for token in tokens) for tokens in exclude_tokens)
                if matched_exclude:
                    continue
                try:
                    return float(value)
                except Exception:
                    continue
        return None

    @staticmethod
    def _pick_text_from_rows(rows: list[dict | None], include_tokens: list[tuple[str, ...]]) -> str | None:
        for row in rows:
            if not row:
                continue
            for key, value in row.items():
                key_norm = re.sub(r"[^a-z0-9]+", "", str(key).lower())
                if any(all(token in key_norm for token in tokens) for tokens in include_tokens):
                    text_value = str(value).strip()
                    if text_value:
                        return text_value[:255]
        return None

    @staticmethod
    def _find_value_by_aliases(normalized_values: dict[str, float], aliases: list[str]) -> float:
        for alias in aliases:
            key = re.sub(r"[^a-z0-9]+", "", alias.lower())
            if key in normalized_values:
                return float(normalized_values[key])
        return 0.0

    @staticmethod
    def _find_value_by_tokens(
        normalized_values: dict[str, float],
        include_groups: list[tuple[str, ...]],
    ) -> float:
        for key, value in normalized_values.items():
            if any(all(token in key for token in include) for include in include_groups):
                return float(value)
        return 0.0

    def _fetch_financial_vnstock(self, symbol: str, snapshot_date: date) -> FinancialData:
        from vnstock import Vnstock

        stock = Vnstock().stock(symbol=symbol, source="VCI")
        ratio_df = stock.finance.ratio(period="year")
        cf_df = stock.finance.cash_flow(period="year")

        ratio_df = self._flatten_columns(ratio_df)
        cf_df = self._flatten_columns(cf_df)

        ratio_row = ratio_df.iloc[0] if ratio_df is not None and len(ratio_df) else {}
        cf_row = cf_df.iloc[0] if cf_df is not None and len(cf_df) else {}

        roe_raw = float(self._pick(ratio_row, ["ROE (%)", "roe", "ROE"], 12) or 12)
        roa_raw = float(self._pick(ratio_row, ["ROA (%)", "roa", "ROA"], 6) or 6)
        roe = roe_raw * 100 if roe_raw <= 1 else roe_raw
        roa = roa_raw * 100 if roa_raw <= 1 else roa_raw
        operating_cf = float(
            self._pick(
                cf_row,
                [
                    "Net cash inflows/outflows from operating activities",
                    "operating_cash_flow",
                ],
                0,
            )
            or 0
        )
        investing_cf = float(self._pick(cf_row, ["Net Cash Flows from Investing Activities", "investing_cash_flow"], 0) or 0)
        free_cf = operating_cf + investing_cf

        red_flags = []
        debt_to_equity = float(self._pick(ratio_row, ["Debt/Equity", "debt_to_equity"], 1.0) or 1.0)
        if debt_to_equity > 2:
            red_flags.append("Debt/Equity cao")
        if operating_cf < 0:
            red_flags.append("Dòng tiền kinh doanh âm")

        pe_value = float(self._pick(ratio_row, ["P/E", "pe_ratio", "pe"], 12) or 12)
        pb_value = float(self._pick(ratio_row, ["P/B", "pb_ratio", "pb"], 1.5) or 1.5)
        current_ratio = float(self._pick(ratio_row, ["Current Ratio", "current_ratio"], 1.2) or 1.2)
        eps_value = float(self._pick(ratio_row, ["EPS (VND)", "eps", "EPS"], 2500) or 2500)

        return FinancialData(
            symbol=symbol,
            snapshot_date=snapshot_date,
            pe=pe_value,
            pb=pb_value,
            roe=roe,
            roa=roa,
            debt_to_equity=debt_to_equity,
            current_ratio=current_ratio,
            operating_cash_flow=operating_cf,
            free_cash_flow=free_cf,
            revenue_growth=float(self._pick(ratio_row, ["revenue_growth", "Revenue Growth"], 0) or 0),
            profit_growth=float(self._pick(ratio_row, ["profit_growth", "Profit Growth"], 0) or 0),
            eps=eps_value,
            auditor_opinion="unknown",
            red_flags=red_flags,
        )

    def _fetch_news_vnstock(self, symbol: str, limit: int) -> list[NewsItem]:
        from vnstock import Vnstock

        stock = Vnstock().stock(symbol=symbol, source="VCI")
        news_df = stock.company.news()
        if news_df is None or len(news_df) == 0:
            return []

        news_df = self._flatten_columns(news_df)
        items: list[NewsItem] = []
        for _, row in news_df.head(limit).iterrows():
            title = str(self._pick(row, ["title", "news_title", "headline"], ""))
            summary = str(self._pick(row, ["summary", "description", "head"], title))
            url = self._pick(row, ["url", "link"], None)
            published = self._pick(row, ["publish_time", "public_date", "time", "date"], datetime.utcnow().isoformat())
            try:
                dt_value = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            except Exception:
                dt_value = datetime.utcnow()

            items.append(
                NewsItem(
                    symbol=symbol,
                    title=title[:500],
                    url=str(url) if url else None,
                    summary=summary[:1200],
                    sentiment="neutral",
                    published_at=dt_value,
                )
            )
        return items

    @staticmethod
    def _flatten_columns(df: pd.DataFrame | None) -> pd.DataFrame:
        if df is None:
            return pd.DataFrame()
        try:
            raw_columns = df.columns
        except Exception:
            return df
        if isinstance(raw_columns, pd.MultiIndex):
            flattened = [c[-1] if isinstance(c, tuple) else str(c) for c in list(raw_columns)]
            result = df.copy()
            result.columns = flattened
            return result
        return df

    @staticmethod
    def _pick(row, keys: list[str], default=None):
        if row is None:
            return default
        for key in keys:
            if key in row and row.get(key) is not None:
                return row.get(key)
        return default

    def _register_vnstock_user(self) -> None:
        api_key = (self.settings.vnstock_api_key or "").strip()
        if not api_key:
            return

        try:
            from vnstock import register_user

            register_user(api_key=api_key)
            logger.info("vnstock_api_key_registered")
        except Exception as exc:
            logger.warning("vnstock_register_user_failed: %s", exc)

    def _throttle(self) -> None:
        while True:
            now = time.time()
            with DataProvider._global_throttle_lock:
                while DataProvider._global_request_timestamps and now - DataProvider._global_request_timestamps[0] >= 60:
                    DataProvider._global_request_timestamps.popleft()

                if len(DataProvider._global_request_timestamps) < self._max_requests_per_min:
                    DataProvider._global_request_timestamps.append(now)
                    return

                wait_seconds = 60 - (now - DataProvider._global_request_timestamps[0]) + 0.3

            if wait_seconds > 0:
                logger.info("vnstock_throttle_sleep %.1fs", wait_seconds)
                time.sleep(wait_seconds)

    @classmethod
    def current_quota_state(cls, max_requests_per_min: int) -> tuple[int, int]:
        now = time.time()
        with cls._global_throttle_lock:
            while cls._global_request_timestamps and now - cls._global_request_timestamps[0] >= 60:
                cls._global_request_timestamps.popleft()
            used = len(cls._global_request_timestamps)
            if used < max_requests_per_min:
                wait_seconds = 0
            else:
                wait_seconds = int(max(1, 60 - (now - cls._global_request_timestamps[0]) + 0.3))
            return used, wait_seconds

    def _call_with_retry(self, fn, op_name: str, symbol: str):
        last_error: BaseException | None = None
        for attempt in range(1, self._retry_attempts + 1):
            self._throttle()
            try:
                return fn()
            except BaseException as exc:
                if isinstance(exc, KeyboardInterrupt):
                    raise
                last_error = exc
                message = str(exc)
                wait_seconds = self._extract_rate_limit_wait_seconds(message)
                rate_limited = self._is_rate_limit_error(message)
                transient_error = self._is_transient_error(message)
                retryable = rate_limited or transient_error

                if not retryable:
                    logger.exception("%s failed symbol=%s attempt=%s", op_name, symbol, attempt)
                    break

                if attempt >= self._retry_attempts:
                    logger.warning(
                        "%s skip_after_max_retry symbol=%s attempts=%s error=%s",
                        op_name,
                        symbol,
                        attempt,
                        message,
                    )
                    break

                if wait_seconds is None:
                    wait_seconds = min(20, 2 * attempt)
                wait_seconds = max(1, wait_seconds)
                logger.warning(
                    "%s retry symbol=%s attempt=%s wait=%ss reason=%s",
                    op_name,
                    symbol,
                    attempt,
                    wait_seconds,
                    "rate_limit" if rate_limited else "transient_error",
                )
                time.sleep(wait_seconds)

        raise RuntimeError(f"{op_name} failed for {symbol}: {last_error}") from last_error

    @staticmethod
    def _is_rate_limit_error(message: str) -> bool:
        text = message.lower()
        keywords = [
            "rate limit",
            "too many requests",
            "quota",
            "gioi han",
            "giới hạn",
            "429",
        ]
        return any(k in text for k in keywords)

    @staticmethod
    def _is_transient_error(message: str) -> bool:
        text = message.lower()
        keywords = [
            "502",
            "503",
            "504",
            "bad gateway",
            "gateway timeout",
            "temporarily unavailable",
            "timeout",
            "connection reset",
            "connection aborted",
            "remote end closed",
        ]
        return any(k in text for k in keywords)

    @staticmethod
    def _extract_rate_limit_wait_seconds(message: str) -> int | None:
        patterns = [
            r"[Cc]hờ\s+(\d+)\s+giây",
            r"[Ww]ait\s+(\d+)\s+seconds",
            r"retry\s+after\s+(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                try:
                    return int(match.group(1)) + 1
                except Exception:
                    return None
        return None
