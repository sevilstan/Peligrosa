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

    # Stay inside the provider's limits (Groq free tier: 30 requests/minute).
    # Extra requests wait in line; after AI_MAX_QUEUE_WAIT_SECONDS the user is
    # asked to try again. Counted per process: run one bot per API key.
    AI_MAX_REQUESTS_PER_MINUTE: int = 25
    AI_MAX_CONCURRENT_REQUESTS: int = 4
    AI_MAX_QUEUE_WAIT_SECONDS: float = 60.0

    # Credits. Off = no limits (development). When on, every new user gets
    # TRIAL_CREDITS once; a subscriber spends nothing but is capped per day.
    CREDITS_ENABLED: bool = False
    TRIAL_CREDITS: int = 10
    MESSAGE_COST: int = 1
    GROUP_MESSAGE_COST: int = 2
    GROUP_CREATE_COST: int = 50
    IMAGE_COST: int = 5
    # Subscription ("sub"): bought with Telegram Stars. Nothing is unlimited:
    # messages are included only up to the daily cap.
    SUB_PRICE_STARS: int = 400  # 0 = no subscription on sale
    SUB_DAYS: int = 30
    SUB_DAILY_MESSAGE_CAP: int = 100
    SUB_GROUP_CREATE_FREE: bool = True
    SUB_BONUS_CREDITS: int = 0  # credits that come with each purchase
    # Credit packs for sale, "credits:stars" separated by commas.
    CREDIT_PACKS: str = "100:50,300:125,1000:350"
    SUPPORT_CONTACT: str = ""  # shown by /support and /paysupport (e.g. @name)
    ADMIN_TELEGRAM_IDS: str = ""  # comma separated Telegram ids who may grant credits

    # Secret salt that turns user ids into pseudonyms in training exports.
    # Keep it private and never change it (old exports would stop matching).
    TRAINING_EXPORT_SALT: str = ""

    # Alerts: ERRORs from our code are sent to ADMIN_TELEGRAM_IDS (each operator
    # must have pressed /start in the bot once).
    ALERT_DEDUP_SECONDS: int = 600
    ALERT_MAX_PER_HOUR: int = 20

    # Health endpoint (GET /health, /stats) for uptime checks. 0 = off.
    HEALTH_PORT: int = 0
    HEALTH_HOST: str = "127.0.0.1"

    # Database connections. A chat reply keeps its connection while the AI
    # answers, so this bounds how many conversations can be in flight.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )


settings = Settings()
