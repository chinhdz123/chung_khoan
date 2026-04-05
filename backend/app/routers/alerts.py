from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert
from app.schemas import AlertOut
from app.services.user_service import ensure_default_user


router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(limit: int = 50, db: Session = Depends(get_db)):
    user = ensure_default_user(db)
    rows = db.execute(
        select(Alert)
        .where(Alert.user_id == user.id)
        .order_by(desc(Alert.created_at))
        .limit(limit)
    ).scalars().all()
    cleaned = []
    for row in rows:
        # Hide legacy alerts generated before unit/policy normalization.
        if "theo % tổng tài sản" in (row.message or ""):
            continue
        if row.alert_type == "buy_signal" and row.current_price and row.trigger_price:
            if row.current_price < 1000 and row.trigger_price > 1000:
                continue
        cleaned.append(row)
    return cleaned


@router.post("/{alert_id}/read")
def mark_alert_read(alert_id: int, db: Session = Depends(get_db)):
    user = ensure_default_user(db)
    alert = db.get(Alert, alert_id)
    if not alert or alert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.is_read = True
    db.commit()
    return {"ok": True}
