from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from app.core.config import settings

engine = None
SessionLocal = None

if settings.DATABASE_URL:
    # SQL logging is controlled in app.core.logging_config (SQL_ECHO), not
    # with echo=True: echo adds its own handler and prints every line twice.
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
    )

    SessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
