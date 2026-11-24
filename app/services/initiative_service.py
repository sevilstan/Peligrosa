"""A character writes first (opt-in, rare, polite).

Rules, all checked here so they are testable without Telegram or a clock:

- the user opted in (users.proactive_enabled) and the account is active;
- not during quiet hours (in the configured UTC offset: Telegram does not
  tell us the user's time zone);
- only in the user's ACTIVE chat, which must have messages;
- the chat has been silent for at least `min_idle_hours` and not longer than
  `max_idle_days` (after that the user has probably left: do not nag);
- never two initiatives in a row without an answer;
- at most one initiative per user per `min_gap_hours`.

Initiative messages are stored with message_type "initiative", which is how
the rules above recognise them. Direct chat: that character writes. Group:
one random member writes, in its own voice and with its own memories and
feelings (the normal group prompt).
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.conversation import Conversation
from app.models.message import Message
from app.services.chat_session_service import ChatSessionService
from app.services.conversation_service import (
    RECENT_MESSAGE_LIMIT,
    AIResponseError,
    ConversationService,
)
from app.services.group_conversation_service import GroupConversationService

logger = logging.getLogger(__name__)

INITIATIVE_MESSAGE_TYPE = "initiative"


@dataclass(frozen=True)
class InitiativeConfig:
    min_idle_hours: float = 6.0
    max_idle_days: float = 7.0
    min_gap_hours: float = 24.0
    quiet_start_hour: int = 22
    quiet_end_hour: int = 9
    utc_offset_hours: int = 3

    @classmethod
    def from_settings(cls, settings):
        return cls(
            min_idle_hours=settings.INITIATIVE_MIN_IDLE_HOURS,
            max_idle_days=settings.INITIATIVE_MAX_IDLE_DAYS,
            min_gap_hours=settings.INITIATIVE_MIN_GAP_HOURS,
            quiet_start_hour=settings.INITIATIVE_QUIET_START_HOUR,
            quiet_end_hour=settings.INITIATIVE_QUIET_END_HOUR,
            utc_offset_hours=settings.INITIATIVE_UTC_OFFSET_HOURS,
        )


@dataclass(frozen=True)
class InitiativeMessage:
    conversation_id: object
    is_group: bool
    speaker_name: str
    content: str


def in_quiet_hours(now: datetime, config: InitiativeConfig) -> bool:
    hour = (now.astimezone(timezone.utc) + timedelta(hours=config.utc_offset_hours)).hour
    start, end = config.quiet_start_hour, config.quiet_end_hour

    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # crosses midnight, e.g. 22 -> 9


class InitiativeService:
    def __init__(self, session, ai_provider, config: InitiativeConfig | None = None, rng=random.choice):
        self.session = session
        self.config = config or InitiativeConfig()
        self.rng = rng
        self.engine = ConversationService(session, ai_provider=ai_provider)
        self.groups = GroupConversationService(session, ai_provider=ai_provider)

    async def run_for_user(self, user, now: datetime | None = None) -> InitiativeMessage | None:
        """Write to this user if every rule allows it; None otherwise."""
        now = now or datetime.now(timezone.utc)

        if not (user.proactive_enabled and user.is_active):
            return None
        if in_quiet_hours(now, self.config):
            return None

        active = await ChatSessionService(self.session).get_active(user.id)
        if active is None:
            return None

        last = (
            await self.session.execute(
                select(Message)
                .where(Message.conversation_id == active.conversation_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if last is None or last.message_type == INITIATIVE_MESSAGE_TYPE:
            return None  # nothing to pick up from, or the last one is unanswered

        idle = now - last.created_at
        if idle < timedelta(hours=self.config.min_idle_hours):
            return None
        if idle > timedelta(days=self.config.max_idle_days):
            return None

        last_initiative = (
            await self.session.execute(
                select(func.max(Message.created_at))
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.user_id == user.id,
                    Message.message_type == INITIATIVE_MESSAGE_TYPE,
                )
            )
        ).scalar_one()
        if last_initiative is not None and now - last_initiative < timedelta(hours=self.config.min_gap_hours):
            return None

        directive = (
            f"The user has not written for about {max(1, int(idle.total_seconds() // 3600))} hours. "
            "Write the short message you would send to start a conversation "
            "(one or two sentences, in your own voice and language, fitting your mood "
            "and what you remember about them or your last talk). Be natural: do not "
            "announce that time has passed and do not ask several questions."
        )

        try:
            if active.is_group:
                return await self._group_message(active.conversation_id, user, directive)
            return await self._direct_message(active.conversation_id, user, directive)
        except (AIResponseError, ValueError) as exc:
            # No reply from the model, or the chat is not usable (a member was
            # deactivated): skip this user for now.
            logger.warning("Initiative skipped: %s", type(exc).__name__)
            await self.session.rollback()
            return None

    async def _direct_message(self, conversation_id, user, directive) -> InitiativeMessage:
        conversation, character = await self.engine._load_direct_conversation(conversation_id, user.id)

        history = (
            await self.session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at, Message.id)
            )
        ).scalars().all()

        recent = history[conversation.summary_message_count :][-RECENT_MESSAGE_LIMIT:]
        ai_messages = [
            {"role": "user" if m.sender_type == "user" else "assistant", "content": m.content}
            for m in recent
        ]
        # The conversation ends with the character's own line: give the model
        # a turn to answer, otherwise some models just continue that line.
        ai_messages.append(
            {"role": "user", "content": "(The user is away. Write the message you would send first.)"}
        )

        system_prompt = await self.engine.build_system_prompt(
            conversation=conversation,
            character=character,
            user_id=user.id,
            context_text=" ".join(m["content"] for m in ai_messages if m["role"] == "user")[-1500:],
        )
        system_prompt += f"\n\nRIGHT NOW\n{directive}"

        content = await self.engine.generate_reply(system_prompt, ai_messages)

        self.session.add(
            Message(
                conversation_id=conversation_id,
                sender_type="character",
                sender_character_id=character.id,
                content=content,
                message_type=INITIATIVE_MESSAGE_TYPE,
            )
        )
        await self.session.commit()

        presented = self.groups.gallery.present(character)
        return InitiativeMessage(conversation_id, False, presented.name, content)

    async def _group_message(self, conversation_id, user, directive) -> InitiativeMessage:
        conversation, members, user_name = await self.groups._load(conversation_id, user.id)
        speaker = self.rng(members)
        names = {m.id: m.name for m in members}

        reply = await self.groups._speak(
            conversation,
            members,
            speaker,
            "initiative",
            user.id,
            user_name,
            names,
            None,
            directive=directive,
            message_type=INITIATIVE_MESSAGE_TYPE,
        )
        return InitiativeMessage(conversation_id, True, speaker.name, reply.content)
