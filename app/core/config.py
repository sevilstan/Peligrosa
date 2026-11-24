from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Peligrosa"
    APP_ENV: str = "development"
    DEBUG: bool = False

    TELEGRAM_BOT_TOKEN: str = ""

    DATABASE_URL: str = ""

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4.1-mini"

    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-20b"

    # Print every SQL statement. Off by default and independent of DEBUG:
    # statements carry parameters, which include users' message text.
    SQL_ECHO: bool = False

    # Applies to every AI provider call (chat replies, summaries, memory
    # extraction). A slow provider must not hang a conversation forever.
    AI_REQUEST_TIMEOUT_SECONDS: float = 30.0
    AI_MAX_RETRIES: int = 2

    # Characters writing first (initiative). Off until the operator enables it,
    # and even then only for users who opted in with /proactive.
    INITIATIVE_ENABLED: bool = False
    INITIATIVE_CHECK_SECONDS: int = 900
    INITIATIVE_MIN_IDLE_HOURS: float = 6.0  # silence before a character may write
    INITIATIVE_MAX_IDLE_DAYS: float = 7.0  # after this the user is considered gone
    INITIATIVE_MIN_GAP_HOURS: float = 24.0  # at most one initiative per user per gap
    INITIATIVE_QUIET_START_HOUR: int = 22  # no initiative between start and end
    INITIATIVE_QUIET_END_HOUR: int = 9
    INITIATIVE_UTC_OFFSET_HOURS: int = 3  # Telegram does not tell us the time zone
    INITIATIVE_MAX_PER_CHECK: int = 5  # cost guard per check

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )


settings = Settings()
