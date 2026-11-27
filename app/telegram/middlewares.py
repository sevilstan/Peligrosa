import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.user_event import UserEvent
from app.services.event_log import event_name
from app.services.telegram_user_service import TelegramUserService
from app.telegram.chat_utils import UserLocks
from app.telegram.texts import all_labels

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

        # A pre-checkout query (payment approval) has a user but no chat.
        needs_private_chat = event.pre_checkout_query is None

        if (
            tg_user is None
            or tg_user.is_bot
            or (needs_private_chat and (chat is None or chat.type != "private"))
        ):
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


_MENU_LABELS = (
    all_labels("menu_characters") | all_labels("menu_chats") | all_labels("menu_history")
)


class ChatOrderMiddleware(BaseMiddleware):
    """Answer a user's chat messages one at a time, in the order they came.

    Telegram updates are handled concurrently, so two quick messages would
    otherwise run side by side and their replies could swap places. This is
    the outermost middleware on purpose: tasks start in arrival order, and
    the lock is taken before any database work that could reorder them.
    Commands, menu buttons and inline buttons are not held back.
    """

    def __init__(self, locks: UserLocks):
        self.locks = locks

    async def __call__(self, handler: Handler, event: Update, data: dict[str, Any]):
        message = event.message

        is_chat_text = (
            message is not None
            and message.from_user is not None
            and bool(message.text)
            and not message.text.startswith("/")
            and message.text not in _MENU_LABELS
        )

        if not is_chat_text:
            return await handler(event, data)

        async with self.locks.for_user(message.from_user.id):
            return await handler(event, data)


class EventMiddleware(BaseMiddleware):
    """Records which command or button was used (by name, see event_log.py).

    Runs after UserMiddleware. Logging must never break the bot: it uses its
    own short session (a failed insert cannot expire the request's objects or
    poison its transaction) and any failure is swallowed after a warning that
    names only the error type.
    """

    def __init__(self, session_maker: async_sessionmaker[AsyncSession], known_commands: set[str]):
        self.session_maker = session_maker
        self.known_commands = known_commands

    async def __call__(self, handler: Handler, event: Update, data: dict[str, Any]):
        name = event_name(event, self.known_commands)
        user = data.get("user")
        if name is not None and user is not None:
            try:
                async with self.session_maker() as session:
                    session.add(UserEvent(user_id=user.id, name=name))
                    await session.commit()
            except Exception as exc:
                logger.warning("Could not record an event: %s", type(exc).__name__)
        return await handler(event, data)
