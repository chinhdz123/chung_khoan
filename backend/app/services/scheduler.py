import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import PortfolioPosition, User, WatchlistSymbol
from app.services.advice_service import AdviceService
from app.services.etl import DailyETLService
from app.utils import vn_today


logger = logging.getLogger(__name__)


def _collect_symbols(db) -> list[str]:
    watchlist_symbols = db.execute(select(WatchlistSymbol.symbol)).scalars().all()
    position_symbols = db.execute(select(PortfolioPosition.symbol)).scalars().all()
    combined = sorted({*(s.upper() for s in watchlist_symbols), *(s.upper() for s in position_symbols)})
    if not combined:
        combined = ["VCB", "FPT", "HPG", "VNM", "TCB"]
    return combined


def run_daily_etl_job() -> None:
    logger.info("scheduler_job_start name=daily_etl")
    db = SessionLocal()
    try:
        service = DailyETLService()
        run_date = vn_today()
        symbols = _collect_symbols(db)
        result = service.run(
            db,
            symbols=symbols,
            run_date=run_date,
            include_financial=False,
            include_news=False,
        )
        logger.info("scheduler_job_done name=daily_etl result=%s", result)
    except Exception as exc:
        logger.exception("scheduler_job_error name=daily_etl error=%s", exc)
        db.rollback()
    finally:
        db.close()


def run_daily_advice_job() -> None:
    logger.info("scheduler_job_start name=daily_advice")
    db = SessionLocal()
    try:
        service = AdviceService()
        run_date = vn_today()
        users_count = len(db.execute(select(User.id)).all())
        if users_count == 0:
            logger.warning("scheduler_job_skip name=daily_advice reason=no_users")
            return
        result = service.run_for_all_users(db, run_date=run_date)
        logger.info("scheduler_job_done name=daily_advice result=%s", result)
    except Exception as exc:
        logger.exception("scheduler_job_error name=daily_advice error=%s", exc)
        db.rollback()
    finally:
        db.close()


def build_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    timezone = ZoneInfo(settings.tz)

    scheduler = BackgroundScheduler(timezone=timezone)
    scheduler.add_job(
        run_daily_etl_job,
        trigger=CronTrigger(hour=settings.etl_hour, minute=settings.etl_minute, timezone=timezone),
        id="daily_etl",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        run_daily_advice_job,
        trigger=CronTrigger(hour=settings.advice_hour, minute=settings.advice_minute, timezone=timezone),
        id="daily_advice",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )
    return scheduler
