import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, ErrorEvent, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.telegram.avatars import AvatarProvider
from app.telegram.chat_utils import UserLocks
from app.telegram.handlers import build_router
from app.telegram.middlewares import ChatOrderMiddleware, DbSessionMiddleware, UserMiddleware
from app.telegram.texts import TEXTS, resolve_language, t

logger = logging.getLogger(__name__)

_COMMANDS = (
    ("start", "cmd_start"),
    ("characters", "cmd_characters"),
    ("chats", "cmd_chats"),
    ("new", "cmd_new"),
)


def build_bot(token: str) -> Bot:
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher(
    session_maker: async_sessionmaker[AsyncSession],
    ai_provider=None,
    avatars: AvatarProvider | None = None,
) -> Dispatcher:
    # Everything handlers need beyond the update itself is injected by name.
    dispatcher = Dispatcher(
        provider=ai_provider,
        avatars=avatars or AvatarProvider(),
    )

    # Order matters: message ordering first (before any database work),
    # then the session, then the user that needs it.
    dispatcher.update.outer_middleware(ChatOrderMiddleware(UserLocks()))
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_maker))
    dispatcher.update.outer_middleware(UserMiddleware())
    dispatcher.include_router(build_router())

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> bool:
        # Log the type only: exceptions can carry user text (SQL parameters).
        logger.error("Unhandled error while processing an update: %s", type(event.exception).__name__)
        await _tell_user_about_error(event)
        return True

    return dispatcher


async def _tell_user_about_error(event: ErrorEvent) -> None:
    """Best effort: a silent bot feels broken."""
    update = event.update
    try:
        if update.message is not None:
            language = update.message.from_user.language_code if update.message.from_user else None
            await update.message.answer(t(resolve_language(language), "error"))
        elif update.callback_query is not None:
            language = update.callback_query.from_user.language_code
            await update.callback_query.answer(t(resolve_language(language), "error"))
    except Exception as exc:
        logger.warning("Could not send the error notice: %s", type(exc).__name__)


async def set_commands(bot: Bot) -> None:
    """The "/" menu next to the message box, in English and Turkish."""
    try:
        for language in TEXTS:
            commands = [
                BotCommand(command=name, description=t(language, key)) for name, key in _COMMANDS
            ]
            await bot.set_my_commands(
                commands, language_code=None if language == "en" else language
            )
    except Exception as exc:
        logger.warning("Could not set the bot command menu: %s", type(exc).__name__)


async def run() -> None:
    from app.database.session import SessionLocal
    from app.providers.groq_provider import GroqProvider

    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to your .env file.")
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")

    # Fails early with a clear message when GROQ_API_KEY is missing.
    provider = GroqProvider()

    bot = build_bot(settings.TELEGRAM_BOT_TOKEN)
    dispatcher = build_dispatcher(SessionLocal, ai_provider=provider)

    try:
        await set_commands(bot)
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        await bot.session.close()
