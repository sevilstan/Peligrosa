"""Background loop that lets characters write first (see InitiativeService).

Runs inside the bot process. Every check it looks at the users who opted in
(/proactive on), lets InitiativeService apply its rules, and sends what comes
out. Each check is capped (INITIATIVE_MAX_PER_CHECK) so cost stays bounded.

A user who is in the middle of a conversation (their per-user lock is held)
is skipped: the character must never talk over a live exchange.
"""

import asyncio
import html
import logging
import random

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.user import User
from app.services.initiative_service import InitiativeConfig, InitiativeMessage, InitiativeService
from app.telegram.chat_utils import UserLocks, split_text

logger = logging.getLogger(__name__)


class InitiativeRunner:
    def __init__(
        self,
        bot: Bot,
        session_maker: async_sessionmaker[AsyncSession],
        ai_provider,
        locks: UserLocks,
        config: InitiativeConfig,
        check_seconds: int,
        max_per_check: int,
        rng=random.Random(),
        choose_speaker=random.choice,
    ):
        self.bot = bot
        self.session_maker = session_maker
        self.ai_provider = ai_provider
        self.locks = locks
        self.config = config
        self.check_seconds = check_seconds
        self.max_per_check = max_per_check
        self.rng = rng
        self.choose_speaker = choose_speaker  # which group member writes

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Initiative check failed: %s", type(exc).__name__)
            await asyncio.sleep(self.check_seconds)

    async def run_once(self) -> int:
        """One check. Returns how many messages were sent."""
        async with self.session_maker() as session:
            rows = (
                await session.execute(
                    select(User.id, User.telegram_id).where(
                        User.proactive_enabled.is_(True),
                        User.is_active.is_(True),
                        User.telegram_id.is_not(None),
                    )
                )
            ).all()

        self.rng.shuffle(rows)  # nobody is always first in line
        sent = 0

        for user_id, telegram_id in rows:
            if sent >= self.max_per_check:
                break
            if await self._write_to(user_id, telegram_id):
                sent += 1

        return sent

    async def _write_to(self, user_id, telegram_id: int) -> bool:
        lock = self.locks.for_user(telegram_id)
        if lock.locked():
            return False  # a live conversation is going on

        async with lock:
            async with self.session_maker() as session:
                user = await session.get(User, user_id)
                if user is None:
                    return False

                try:
                    message = await InitiativeService(
                        session, self.ai_provider, self.config, rng=self.choose_speaker
                    ).run_for_user(user)
                except Exception as exc:
                    logger.warning("Initiative failed for a user: %s", type(exc).__name__)
                    await session.rollback()
                    return False

                if message is None:
                    return False

                try:
                    await self._send(telegram_id, message)
                except TelegramForbiddenError:
                    # The user blocked the bot: stop trying.
                    user.proactive_enabled = False
                    await session.commit()
                    logger.info("A user blocked the bot; proactive messages turned off for them.")
                    return False
                except TelegramAPIError as exc:
                    logger.warning("Could not deliver an initiative message: %s", type(exc).__name__)
                    return False

                return True

    async def _send(self, chat_id: int, message: InitiativeMessage) -> None:
        parts = split_text(message.content)

        if message.is_group:
            # Same look as group replies: the name opens the message.
            header = f"<b>{html.escape(message.speaker_name)}:</b> "
            await self.bot.send_message(chat_id, header + html.escape(parts[0]), parse_mode="HTML")
            parts = parts[1:]

        for part in parts:
            await self.bot.send_message(chat_id, part, parse_mode=None)
