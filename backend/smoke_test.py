import os
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn
from sqlalchemy import desc, select

os.environ["GEMINI_ENABLED"] = "false"
os.environ["SQLITE_PATH"] = "./data/smoke_test.db"

from app.database import SessionLocal
from app.main import app
from app.models import FinancialSnapshot, MarketSnapshot
from app.utils import vn_today


BASE_URL = "http://127.0.0.1:8010"
SMOKE_DB_PATH = Path(__file__).resolve().parent / "data" / "smoke_test.db"


def request_json(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)

    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode("utf-8")
        return resp.getcode(), json.loads(body)


def request_text(method: str, path: str) -> tuple[int, str]:
    req = urllib.request.Request(f"{BASE_URL}{path}", method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode("utf-8")
        return resp.getcode(), body


def wait_for_server(max_wait_seconds: int = 20) -> None:
    start = time.time()
    while time.time() - start < max_wait_seconds:
        try:
            code, payload = request_json("GET", "/api/health")
            if code == 200 and payload.get("ok"):
                return
        except Exception:
            time.sleep(0.5)
    raise TimeoutError("Server did not start in time")


def ensure_minimum_snapshots(symbols: list[str]) -> None:
    run_date = vn_today()
    db = SessionLocal()
    try:
        for idx, symbol in enumerate(symbols):
            market_row = db.execute(
                select(MarketSnapshot)
                .where(MarketSnapshot.symbol == symbol)
                .order_by(desc(MarketSnapshot.snapshot_date))
                .limit(1)
            ).scalar_one_or_none()
            if not market_row:
                base_price = 100 + (idx * 3)
                db.add(
                    MarketSnapshot(
                        symbol=symbol,
                        snapshot_date=run_date,
                        open_price=base_price - 1,
                        high_price=base_price + 1,
                        low_price=base_price - 2,
                        close_price=base_price,
                        volume=1_000_000 + (idx * 10_000),
                        foreign_net_value=0,
                        proprietary_net_value=0,
                        retail_estimated_value=base_price * 1_000_000,
                    )
                )

            fin_row = db.execute(
                select(FinancialSnapshot)
                .where(FinancialSnapshot.symbol == symbol)
                .order_by(desc(FinancialSnapshot.snapshot_date))
                .limit(1)
            ).scalar_one_or_none()
            if not fin_row:
                db.add(
                    FinancialSnapshot(
                        symbol=symbol,
                        snapshot_date=run_date,
                        pe=12,
                        pb=1.6,
                        roe=16,
                        roa=7,
                        debt_to_equity=0.8,
                        current_ratio=1.4,
                        operating_cash_flow=100000000,
                        free_cash_flow=50000000,
                        revenue_growth=0.1,
                        profit_growth=0.08,
                        eps=3000,
                        auditor_opinion="clean",
                        red_flags_json="[]",
                    )
                )
        db.commit()
    finally:
        db.close()


def run() -> None:
    if SMOKE_DB_PATH.exists():
        SMOKE_DB_PATH.unlink()

    config = uvicorn.Config(app=app, host="127.0.0.1", port=8010, log_level="warning")
    server = uvicorn.Server(config=config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        wait_for_server()

        code, health = request_json("GET", "/api/health")
        assert code == 200 and health["ok"] is True

        code, html = request_text("GET", "/")
        assert code == 200 and "KyLuat" in html

        code, list_page = request_text("GET", "/stocks")
        assert code == 200 and "stockTableBody" in list_page

        code, settings_page = request_text("GET", "/settings")
        assert code == 200 and "stockTableBody" in settings_page

        code, watchlist_settings = request_text("GET", "/settings/watchlist")
        assert code == 200 and "stockTableBody" in watchlist_settings

        code, holdings_settings = request_text("GET", "/settings/holdings")
        assert code == 200 and "holdingsForm" in holdings_settings

        code, watchlist_config = request_json("GET", "/api/portfolio/watchlist-config")
        assert code == 200 and "watchlist_symbols" in watchlist_config

        code, holdings_config = request_json("GET", "/api/portfolio/holdings-config")
        assert code == 200 and "positions" in holdings_config

        watchlist_payload = {
            "watchlist_symbols": ["VCB", "FPT", "HPG", "VNM", "TCB"],
        }
        code, _ = request_json("PUT", "/api/portfolio/watchlist-config", watchlist_payload)
        assert code == 200

        holdings_payload = {
            "cash": 25000000,
            "target_cash_ratio": 0.5,
            "positions": [
                {"symbol": "VCB", "quantity": 100, "avg_cost": 84, "current_price": 89},
                {"symbol": "FPT", "quantity": 50, "avg_cost": 118, "current_price": 121},
            ],
            "symbol_rules": [
                {
                    "symbol": "VCB",
                    "stop_accumulate_price": 94,
                    "take_profit_price": 128,
                }
            ],
        }
        code, _ = request_json("PUT", "/api/portfolio/holdings-config", holdings_payload)
        assert code == 200

        code, etl = request_json("POST", "/api/jobs/run-etl")
        assert code == 200 and "details" in etl

        # ETL can fail due to provider limits/unavailable network.
        # Seed minimum snapshots for smoke assertions when data is missing.
        ensure_minimum_snapshots(["VCB", "FPT", "HPG", "VNM", "TCB"])

        code, allocation = request_json("GET", "/api/portfolio/allocation")
        assert code == 200 and "stock_ratio" in allocation and "target_stock_ratio" in allocation

        code, snapshot = request_json("GET", "/api/market/VCB/snapshot")
        assert code == 200 and snapshot["symbol"] == "VCB"

        code, watchlist_snapshots = request_json("GET", "/api/market/watchlist-snapshots")
        assert code == 200 and isinstance(watchlist_snapshots, list)

        code, history = request_json("GET", "/api/market/VCB/history?days=5")
        assert code == 200 and isinstance(history, list)

        code, detail_page = request_text("GET", "/stocks/VCB")
        assert code == 200 and 'data-symbol="VCB"' in detail_page

        code, advice_job = request_json("POST", "/api/jobs/run-advice")
        assert code == 200 and advice_job.get("ok") is True

        code, advice = request_json("GET", "/api/advice/latest")
        assert code == 200 and advice.get("report_date")
        assert "summary" in advice and "decisions" in advice

        code, alerts = request_json("GET", "/api/alerts")
        assert code == 200 and isinstance(alerts, list)

        code, health_report = request_json("GET", "/api/portfolio/health")
        assert code == 200 and "risk_score" in health_report

        print("SMOKE_TEST_PASS: Web + API workflow OK")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if SMOKE_DB_PATH.exists():
            SMOKE_DB_PATH.unlink()


if __name__ == "__main__":
    run()
