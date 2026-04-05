import logging
import random
import subprocess
import time

from app.config import get_settings


logger = logging.getLogger(__name__)


def generate_text(prompt: str, model: str | None = None) -> tuple[str, int]:
    settings = get_settings()
    selected_model = model or settings.gemini_model
    max_retries = settings.gemini_max_retries
    timeout_seconds = settings.gemini_timeout_seconds

    last_error = "unknown"
    start_ts = time.time()

    for attempt in range(max_retries + 1):
        try:
            result = subprocess.run(
                [settings.gemini_cmd, "-p", "", "--model", selected_model],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_seconds,
            )

            if result.returncode == 0 and result.stdout.strip():
                latency_ms = int((time.time() - start_ts) * 1000)
                logger.info("gemini_call_ok model=%s latency_ms=%s", selected_model, latency_ms)
                return result.stdout.strip(), latency_ms

            err_msg = result.stderr.strip() if result.stderr else f"returncode={result.returncode}"
            last_error = err_msg
            logger.warning(
                "gemini_call_failed attempt=%s model=%s error=%s",
                attempt + 1,
                selected_model,
                err_msg,
            )

            if "429" in err_msg or "quota" in err_msg.lower() or "resource_exhausted" in err_msg.lower():
                time.sleep(25 * (attempt + 1))
            elif attempt < max_retries:
                time.sleep(random.uniform(2, 6))

        except subprocess.TimeoutExpired:
            last_error = f"timeout>{timeout_seconds}s"
            logger.warning("gemini_timeout attempt=%s", attempt + 1)
            if attempt < max_retries:
                time.sleep(random.uniform(2, 6))
        except Exception as exc:
            last_error = str(exc)
            logger.exception("gemini_exception attempt=%s", attempt + 1)
            if attempt < max_retries:
                time.sleep(random.uniform(2, 6))

    latency_ms = int((time.time() - start_ts) * 1000)
    raise RuntimeError(f"Gemini CLI failed after retries: {last_error}; latency_ms={latency_ms}")
