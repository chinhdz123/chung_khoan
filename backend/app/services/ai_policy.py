import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AdviceReport, AiUsageLog


logger = logging.getLogger(__name__)


class AiPolicy:
    def __init__(self) -> None:
        self.settings = get_settings()

    def get_latest_report(self, db: Session, user_id: int) -> AdviceReport | None:
        return db.execute(
            select(AdviceReport)
            .where(AdviceReport.user_id == user_id)
            .order_by(AdviceReport.report_date.desc())
            .limit(1)
        ).scalar_one_or_none()

    def is_material_change(
        self,
        latest_report: AdviceReport | None,
        state_hash: str,
        max_score_delta: float,
        max_risk_delta: float,
    ) -> bool:
        if latest_report is None:
            return True
        if latest_report.state_hash != state_hash:
            if abs(max_score_delta) >= self.settings.ai_min_score_delta_for_change:
                return True
            if abs(max_risk_delta) >= self.settings.ai_min_risk_delta_for_change:
                return True
        return False

    def _global_calls_today(self, db: Session, run_date: date) -> int:
        return int(
            db.execute(
                select(func.count(AiUsageLog.id)).where(
                    AiUsageLog.run_date == run_date,
                    AiUsageLog.success.is_(True),
                )
            ).scalar_one()
        )

    def _user_calls_today(self, db: Session, user_id: int, run_date: date) -> int:
        return int(
            db.execute(
                select(func.count(AiUsageLog.id)).where(
                    AiUsageLog.run_date == run_date,
                    AiUsageLog.user_id == user_id,
                    AiUsageLog.success.is_(True),
                )
            ).scalar_one()
        )

    def should_call_ai(
        self,
        db: Session,
        user_id: int,
        run_date: date,
        state_hash: str,
        material_change: bool,
    ) -> tuple[bool, str]:
        if not self.settings.gemini_enabled:
            return False, "gemini_disabled"

        if not material_change:
            return False, "no_material_change"

        latest = self.get_latest_report(db, user_id)
        if latest and latest.state_hash == state_hash:
            return False, "same_state_hash"

        global_calls = self._global_calls_today(db, run_date)
        if global_calls >= self.settings.ai_max_calls_global_per_day:
            return False, "global_quota_reached"

        user_calls = self._user_calls_today(db, user_id, run_date)
        if user_calls >= self.settings.ai_max_calls_per_user_per_day:
            return False, "user_quota_reached"

        return True, "eligible"

    @staticmethod
    def log_usage(
        db: Session,
        user_id: int | None,
        run_date: date,
        purpose: str,
        state_hash: str,
        success: bool,
        latency_ms: int,
        error_message: str | None,
    ) -> None:
        db.add(
            AiUsageLog(
                user_id=user_id,
                run_date=run_date,
                purpose=purpose,
                state_hash=state_hash,
                success=success,
                latency_ms=latency_ms,
                error_message=error_message,
            )
        )
        logger.info(
            "ai_usage user=%s date=%s purpose=%s success=%s latency_ms=%s error=%s",
            user_id,
            run_date,
            purpose,
            success,
            latency_ms,
            error_message,
        )
