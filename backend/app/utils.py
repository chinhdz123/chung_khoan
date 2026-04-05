import hashlib
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def vn_now() -> datetime:
    tz = ZoneInfo(get_settings().tz)
    return datetime.now(tz)


def vn_today() -> date:
    return vn_now().date()


def stable_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
