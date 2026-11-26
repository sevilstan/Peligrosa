import asyncio
import contextlib
from collections import defaultdict

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

TELEGRAM_MESSAGE_LIMIT = 4096


def split_text(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split a long reply into Telegram-sized parts, at natural boundaries."""
    text = text.strip()
    parts: list[str] = []

    while len(text) > limit:
        cut = max(
            text.rfind("\n\n", 0, limit),
            text.rfind("\n", 0, limit),
            text.rfind(" ", 0, limit),
        )
        if cut < limit // 2:  # no good boundary: hard cut
            cut = limit
        parts.append(text[:cut].strip())
        text = text[cut:].strip()

    if text:
        parts.append(text)
    return parts


class UserLocks:
    """One lock per user: their messages are answered in the order sent.

    Telegram updates are handled concurrently, so two quick messages would
    otherwise run side by side and their replies could arrive out of order.
    """

    def __init__(self):
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def for_user(self, user_id: int) -> asyncio.Lock:
        return self._locks[user_id]


@contextlib.asynccontextmanager
async def typing_indicator(bot: Bot, chat_id: int, action: str = "typing"):
    """Show "typing…" (or e.g. "upload_photo") while the character works. It
    expires after 5s, so it is repeated."""

    async def keep_typing():
        while True:
            with contextlib.suppress(Exception):
                await bot.send_chat_action(chat_id, action)
            await asyncio.sleep(4)

    task = asyncio.create_task(keep_typing())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def edit_text_in_place(
    callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None
) -> None:
    """Edit the message under a pressed button; a no-op edit is not an error."""
    message = callback.message
    if not isinstance(message, Message):
        return  # inaccessible (old) message: nothing to edit
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
