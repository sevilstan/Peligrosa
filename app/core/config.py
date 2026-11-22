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

    # Applies to every AI provider call (chat replies, summaries, memory
    # extraction). A slow provider must not hang a conversation forever.
    AI_REQUEST_TIMEOUT_SECONDS: float = 30.0
    AI_MAX_RETRIES: int = 2

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )


settings = Settings()
