from fastapi import APIRouter

from app.utils import vn_now


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    now = vn_now()
    return {
        "ok": True,
        "time": now.isoformat(),
        "service": "ky-luat-dau-tu",
    }
