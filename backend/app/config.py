from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = Field(default="KyLuat DauTu", alias="APP_NAME")
    env: str = Field(default="dev", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    sqlite_path: str = Field(default="./data/chung_khoan.db", alias="SQLITE_PATH")
    tz: str = Field(default="Asia/Ho_Chi_Minh", alias="TZ")

    etl_hour: int = Field(default=15, alias="ETL_HOUR")
    etl_minute: int = Field(default=30, alias="ETL_MINUTE")
    advice_hour: int = Field(default=6, alias="ADVICE_HOUR")
    advice_minute: int = Field(default=0, alias="ADVICE_MINUTE")

    gemini_enabled: bool = Field(default=True, alias="GEMINI_ENABLED")
    gemini_cmd: str = Field(default=r"C:\Users\HLC\AppData\Roaming\npm\gemini.cmd", alias="GEMINI_CMD")
    gemini_model: str = Field(default="gemini-3-flash-preview", alias="GEMINI_MODEL")
    gemini_timeout_seconds: int = Field(default=180, alias="GEMINI_TIMEOUT_SECONDS")
    gemini_max_retries: int = Field(default=2, alias="GEMINI_MAX_RETRIES")

    ai_max_calls_global_per_day: int = Field(default=30, alias="AI_MAX_CALLS_GLOBAL_PER_DAY")
    ai_max_calls_per_user_per_day: int = Field(default=1, alias="AI_MAX_CALLS_PER_USER_PER_DAY")
    ai_top_symbols_per_report: int = Field(default=5, alias="AI_TOP_SYMBOLS_PER_REPORT")
    ai_min_score_delta_for_change: float = Field(default=10.0, alias="AI_MIN_SCORE_DELTA_FOR_CHANGE")
    ai_min_risk_delta_for_change: float = Field(default=8.0, alias="AI_MIN_RISK_DELTA_FOR_CHANGE")

    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    email_from: str = Field(default="noreply@example.com", alias="EMAIL_FROM")

    vnstock_api_key: str = Field(default="", alias="VNSTOCK_API_KEY")
    vnstock_max_requests_per_min: int = Field(default=18, alias="VNSTOCK_MAX_REQUESTS_PER_MIN")
    vnstock_retry_attempts: int = Field(default=3, alias="VNSTOCK_RETRY_ATTEMPTS")
    vnstock_enrich_market_flows: bool = Field(default=True, alias="VNSTOCK_ENRICH_MARKET_FLOWS")

    eod_market_api_url: str = Field(
        default="https://api-finfo.vndirect.com.vn/v4/stock_prices",
        alias="EOD_MARKET_API_URL",
    )
    eod_foreign_api_url: str = Field(
        default="https://api-finfo.vndirect.com.vn/v4/foreigns",
        alias="EOD_FOREIGN_API_URL",
    )
    eod_proprietary_api_url: str = Field(
        default="https://api-finfo.vndirect.com.vn/v4/proprietary_trading",
        alias="EOD_PROPRIETARY_API_URL",
    )
    eod_market_max_back_days: int = Field(default=5, alias="EOD_MARKET_MAX_BACK_DAYS")

    @property
    def sqlite_url(self) -> str:
        db_path = Path(self.sqlite_path)
        if not db_path.is_absolute():
            db_path = Path(__file__).resolve().parents[1] / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
