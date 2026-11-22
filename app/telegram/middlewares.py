import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.telegram_user_service import TelegramUserService

logger = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class DbSessionMiddleware(BaseMiddleware):
    """One database session per Telegram update, closed afterwards."""

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        self.session_maker = session_maker

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]):
        async with self.session_maker() as session:
            data["session"] = session
            return await handler(event, data)


class UserMiddleware(BaseMiddleware):
    """Connects the Telegram account to a platform user.

    Registered on dispatcher.update, after aiogram's own context middleware,
    so event_from_user / event_chat are already in `data`. Updates that are
    not from a human in a private chat are dropped here: group chats are a
    later roadmap item and must not be half-handled.
    """

    async def __call__(self, handler: Handler, event: Update, data: dict[str, Any]):
        tg_user = data.get("event_from_user")
        chat = data.get("event_chat")

        if tg_user is None or tg_user.is_bot or chat is None or chat.type != "private":
            return None

        service = TelegramUserService(data["session"])
        user = await service.get_or_create(
            telegram_id=tg_user.id,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            language_code=tg_user.language_code,
        )

        if not user.is_active:
            logger.info("Ignoring update from a deactivated user.")
            return None

        data["user"] = user
        return await handler(event, data)
