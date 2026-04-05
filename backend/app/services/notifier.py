import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings


logger = logging.getLogger(__name__)


def send_in_app_notification(user_id: int, title: str, body: str) -> None:
    logger.info("in_app_notification user_id=%s title=%s body=%s", user_id, title, body)


def send_email_notification(to_email: str, subject: str, body: str) -> bool:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
        logger.warning("email_skipped_missing_smtp to=%s subject=%s", to_email, subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
        logger.info("email_sent to=%s subject=%s", to_email, subject)
        return True
    except Exception as exc:
        logger.exception("email_send_failed to=%s subject=%s error=%s", to_email, subject, exc)
        return False
