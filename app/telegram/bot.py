import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.telegram.handlers import build_router
from app.telegram.middlewares import DbSessionMiddleware, UserMiddleware

logger = logging.getLogger(__name__)


def build_bot(token: str) -> Bot:
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher(session_maker: async_sessionmaker[AsyncSession]) -> Dispatcher:
    dispatcher = Dispatcher()

    # Order matters: the session first, then the user that needs it.
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_maker))
    dispatcher.update.outer_middleware(UserMiddleware())
    dispatcher.include_router(build_router())

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> bool:
        # Log the type only: exceptions can carry user text (SQL parameters).
        logger.error("Unhandled error while processing an update: %s", type(event.exception).__name__)
        return True

    return dispatcher


async def run() -> None:
    from app.database.session import SessionLocal

    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to your .env file.")
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")

    bot = build_bot(settings.TELEGRAM_BOT_TOKEN)
    dispatcher = build_dispatcher(SessionLocal)

    try:
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        await bot.session.close()
