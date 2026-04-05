import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.logging_config import configure_logging
from app.request_context import request_id_ctx
from app.routers import advice, alerts, health, market, portfolio
from app.services.scheduler import build_scheduler
from app.services.user_service import ensure_default_user


settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

scheduler = build_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        ensure_default_user(db)
    finally:
        db.close()

    scheduler.start()
    logger.info("app_started scheduler_running=%s", scheduler.running)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        logger.info("app_shutdown")


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(health.router)
app.include_router(portfolio.router)
app.include_router(market.router)
app.include_router(alerts.router)
app.include_router(advice.router)


@app.middleware("http")
async def attach_request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    token = request_id_ctx.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        logger.exception("request_failed path=%s method=%s error=%s", request.url.path, request.method, exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "internal_error", "request_id": request_id},
        )
    finally:
        request_id_ctx.reset(token)


@app.get("/", response_class=HTMLResponse)
@app.get("/stocks", response_class=HTMLResponse)
def stocks_list_page(request: Request):
    return templates.TemplateResponse("stocks_list.html", {"request": request, "app_name": settings.app_name})


@app.get("/stocks/{symbol}", response_class=HTMLResponse)
def stock_detail_page(request: Request, symbol: str):
    return templates.TemplateResponse(
        "stock_detail.html",
        {"request": request, "app_name": settings.app_name, "symbol": symbol.upper()},
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return RedirectResponse(url="/stocks", status_code=307)


@app.get("/settings/watchlist", response_class=HTMLResponse)
def settings_watchlist_page(request: Request):
    return RedirectResponse(url="/stocks", status_code=307)


@app.get("/settings/holdings", response_class=HTMLResponse)
def settings_holdings_page(request: Request):
    return templates.TemplateResponse("settings_holdings.html", {"request": request, "app_name": settings.app_name})
