import asyncio
import contextlib
from collections import defaultdict

from aiogram import Bot

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
async def typing_indicator(bot: Bot, chat_id: int):
    """Show "typing…" while the character is thinking (it expires after 5s)."""

    async def keep_typing():
        while True:
            with contextlib.suppress(Exception):
                await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)

    task = asyncio.create_task(keep_typing())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
