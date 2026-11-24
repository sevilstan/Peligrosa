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

    # Stay inside the provider's limits (Groq free tier: 30 requests/minute).
    # Extra requests wait in line; after AI_MAX_QUEUE_WAIT_SECONDS the user is
    # asked to try again. Counted per process: run one bot per API key.
    AI_MAX_REQUESTS_PER_MINUTE: int = 25
    AI_MAX_CONCURRENT_REQUESTS: int = 4
    AI_MAX_QUEUE_WAIT_SECONDS: float = 60.0

    # Database connections. A chat reply keeps its connection while the AI
    # answers, so this bounds how many conversations can be in flight.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )


settings = Settings()
