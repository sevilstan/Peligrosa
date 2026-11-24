import logging
import random
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.models.character import Character
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.models.message import Message
from app.models.user import User
from app.services.character_gallery_service import CharacterGalleryService
from app.services.conversation_service import AIResponseError, RECENT_MESSAGE_LIMIT, ConversationService
from app.services.group_context_builder import (
    DEFAULT_USER_NAME,
    character_state_text,
    group_instructions,
    label_messages,
)
from app.services.character_memory_service import CharacterMemoryService
from app.services.character_state_service import (
    CharacterEmotionService,
    CharacterRelationshipService,
)
from app.services.relationship_reflector import RelationshipReflector
from app.services.speaker_director import SILENCE, SpeakerDirector
from app.services.speaker_selection import GroupMember, select_speaker

logger = logging.getLogger(__name__)

_USER_TEXT_FOR_RECALL = 1500


# Cost guard: at most this many characters answer one user message (equals
# the largest group).
MAX_REPLIES_PER_TURN = 4

# Characters sometimes talk to each other (one question + one answer, never a
# chain). Both numbers exist to keep the cost bounded.
FOLLOWUP_CHANCE = 0.25  # share of turns that even check for a follow-up
MAX_TOTAL_REPLIES_PER_TURN = 6  # everything a single user message may cause

# Feelings are updated in one batched call per this many new messages.
REFLECTION_MIN_NEW_MESSAGES = 8


@dataclass(frozen=True)
class GroupReply:
    speaker: GroupMember
    content: str
    reason: str  # "addressed", "director", "everyone" or "followup"
    message_id: object


class GroupConversationService:
    """A user's message in a persistent group, answered by one or more characters.

    Same safety rules as direct chats: the user's message is saved first and
    survives any later failure; memory and summary are best effort; a provider
    failure raises AIResponseError.

    Memory: every character IN the group independently remembers what the user
    said in front of them (one extraction, separate records per character); a
    character's memories are loaded for ITS reply only, with user_id AND
    character_id, and are never shown to the others.
    """

    def __init__(self, session, ai_provider=None, followup_chance=0.0, rng=random.random, reflection=False):
        # followup_chance is 0 by default so that only the Telegram handler
        # (which passes FOLLOWUP_CHANCE) enables it; tests stay deterministic.
        self.followup_chance = followup_chance
        self.reflection = reflection  # off by default, like followups
        self.rng = rng
        self.session = session
        self.engine = ConversationService(session, ai_provider=ai_provider)
        self.gallery = CharacterGalleryService(session)
        self.director = SpeakerDirector(self.engine.ai_provider)
        self.reflector = RelationshipReflector(self.engine.ai_provider)

    async def send_message(self, conversation_id, user_id, content, on_reply=None) -> list[GroupReply]:
        """Save the user's message and let the right characters answer.

        Returns the replies in order (empty = everybody stayed silent).
        on_reply(reply) is awaited after each reply is saved, so a caller can
        deliver it right away while the next character is still "thinking".
        If a later character fails, the replies already given are kept and
        returned; only a failure of the very first reply raises AIResponseError.
        """
        conversation, members, user_name = await self._load(conversation_id, user_id)

        content = content.strip()
        if not content:
            raise ValueError("Mesaj boş olamaz.")

        # Save the user's message first: it must survive any later failure.
        self.session.add(
            Message(
                conversation_id=conversation_id,
                sender_type="user",
                sender_user_id=user_id,
                content=content,
                message_type="text",
            )
        )
        await self.session.commit()

        # Everyone present remembers; the rollback on failure expires ORM
        # objects, so the conversation is reloaded afterwards.
        await self.engine.update_memories(
            user_id, members, content, conversation_id=conversation_id, source_kind="group"
        )
        conversation, members, user_name = await self._load(conversation_id, user_id)

        names = {m.id: m.name for m in members}
        history = await self._messages(conversation_id)

        speakers = await self._who_speaks(content, members, history, names, user_name)
        replies: list[GroupReply] = []

        for member, reason in speakers[:MAX_REPLIES_PER_TURN]:
            try:
                reply = await self._speak(
                    conversation, members, member, reason, user_id, user_name, names, on_reply
                )
            except AIResponseError:
                if not replies:
                    raise
                logger.warning("A character could not answer; keeping the replies so far.")
                break
            replies.append(reply)

        if replies:
            replies += await self._followup(
                conversation, members, user_id, user_name, names, on_reply, len(replies)
            )

        # Best effort, like in direct chats.
        if replies:
            try:
                await self.engine.update_conversation_summary(conversation, speaker_names=names)
            except Exception as exc:
                logger.warning(
                    "Summary update failed, will retry on a later message: %s",
                    type(exc).__name__,
                )
                await self.session.rollback()

            if self.reflection:
                await self._reflect(conversation_id, user_id, members, names, user_name)

        return replies

    async def _reflect(self, conversation_id, user_id, members, names, user_name) -> None:
        """Every few messages: update the characters' feelings from the chat.

        Best effort and atomic. The "messages already reflected on" counter is
        advanced with a compare-and-set INSIDE the same transaction as the
        feelings, so concurrent requests cannot both apply the same batch, and
        a failure leaves both unchanged. A provider error is retried on a later
        message; unusable output is skipped (the counter still advances) so a
        bad answer is not paid for again on every message.
        """
        try:
            conversation = await self.session.get(Conversation, conversation_id)
            await self.session.refresh(conversation)
            previous = conversation.reflection_message_count

            messages = await self._messages(conversation_id)
            if len(messages) - previous < REFLECTION_MIN_NEW_MESSAGES:
                return

            parsed = await self.reflector.reflect(messages[previous:], members, names, user_name)

            claimed = await self.session.execute(
                update(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.reflection_message_count == previous,
                )
                .values(
                    reflection_message_count=len(messages),
                    # Keep updated_at: it marks the chat the user last opened.
                    updated_at=Conversation.updated_at,
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount == 0:
                await self.session.rollback()  # another request took this batch
                return

            if parsed is not None:
                relationships, moods, events = parsed
                relationship_service = CharacterRelationshipService(self.session)
                emotion_service = CharacterEmotionService(self.session)

                for sender, target, deltas in relationships:
                    await relationship_service.apply_deltas(user_id, sender.id, target.id, deltas)
                for member, mood, intensity, reason in moods:
                    await emotion_service.set_emotion(user_id, member.id, mood, intensity, reason)

                # Everyone who was in the group witnessed the event: each one
                # keeps it in ITS OWN memory (separate records), so it can come
                # up in other chats too. Nobody outside the group learns it.
                memory_service = CharacterMemoryService(self.session)
                for key, content, importance in events:
                    for member in members:
                        await memory_service.add_memory(
                            user_id=user_id,
                            character_id=member.id,
                            category="event",
                            content=content,
                            importance=importance,
                            confidence=0.8,
                            memory_key=key,
                            source_conversation_id=conversation_id,
                            source_kind="group",
                        )

            await self.session.commit()
        except Exception as exc:
            logger.warning("Feelings reflection failed, will retry later: %s", type(exc).__name__)
            await self.session.rollback()

    async def _who_speaks(self, content, members, history, names, user_name):
        """[(member, reason)] in reply order.

        Called by name -> only that character. Otherwise the director picks
        (usually everyone); if it cannot, everyone answers, as a group would.
        """
        last_speaker_id = self._last_character_speaker(history[:-1])
        choice = select_speaker(content, members, last_speaker_id)

        if choice.reason == "addressed":
            return [(choice.member, "addressed")]

        decided = await self.director.choose(history, members, names, user_name)

        if decided is SILENCE:
            return []
        if isinstance(decided, list):
            return [(m, "director") for m in decided]

        return [(m, "everyone") for m in members]

    async def _speak(self, conversation, members, speaker, reason, user_id, user_name, names, on_reply, directive=None, message_type="text"):
        """Generate, save and deliver one character message."""
        # Later speakers see the earlier replies of this same turn.
        history = await self._messages(conversation.id)
        reply_text = await self._reply(
            conversation, members, speaker, history, user_id, user_name, names, directive
        )

        character_message = Message(
            conversation_id=conversation.id,
            sender_type="character",
            sender_character_id=speaker.id,
            content=reply_text,
            message_type=message_type,
        )
        self.session.add(character_message)
        await self.session.commit()

        reply = GroupReply(speaker, reply_text, reason, character_message.id)

        if on_reply is not None:
            try:
                await on_reply(reply)
            except Exception as exc:
                # Delivery problems must not cut the conversation short.
                logger.warning("Delivering a group reply failed: %s", type(exc).__name__)

        return reply

    async def _followup(self, conversation, members, user_id, user_name, names, on_reply, already):
        """Sometimes one character turns to another and that one answers.

        At most ONE exchange (two messages) per user message, only some of the
        time, and only within the total reply cap: natural, but cheap.
        Best effort: any failure just means no follow-up.
        """
        if (
            len(members) < 2
            or self.followup_chance <= 0
            or already + 2 > MAX_TOTAL_REPLIES_PER_TURN
            or self.rng() >= self.followup_chance
        ):
            return []

        history = await self._messages(conversation.id)
        pair = await self.director.choose_followup(history, members, names, user_name)
        if pair is None:
            return []
        sender, target = pair

        followups: list[GroupReply] = []
        try:
            followups.append(
                await self._speak(
                    conversation, members, sender, "followup", user_id, user_name, names, on_reply,
                    directive=(
                        f"Right now, say something short directly to {target.name} "
                        "(a question, a tease or a reaction to what they said), "
                        "addressing them by name."
                    ),
                )
            )
            followups.append(
                await self._speak(
                    conversation, members, target, "followup", user_id, user_name, names, on_reply,
                    directive=f"{sender.name} just spoke to you. Answer them briefly.",
                )
            )
        except AIResponseError:
            logger.warning("A follow-up message could not be generated; stopping there.")

        return followups

    # ------------------------------------------------------------ internals

    async def _reply(self, conversation, members, speaker: GroupMember, history, user_id, user_name, names, directive=None) -> str:
        character = next(
            p.character for p in conversation.participants if p.character_id == speaker.id
        )

        unsummarized = history[conversation.summary_message_count :][-RECENT_MESSAGE_LIMIT:]
        recent_user_text = " ".join(m.content for m in unsummarized if m.sender_type == "user")

        base_prompt = await self.engine.build_system_prompt(
            conversation=conversation,
            character=character,
            user_id=user_id,
            context_text=recent_user_text[-_USER_TEXT_FOR_RECALL:],
        )
        system_prompt = f"{base_prompt}\n\n{group_instructions(speaker, members, user_name)}"

        # Only THIS speaker's own feelings: user_id AND character_id.
        feelings = character_state_text(
            await CharacterEmotionService(self.session).get_emotion(user_id, speaker.id),
            await self._relationships_by_name(user_id, speaker, members),
        )
        if feelings:
            system_prompt += f"\n\n{feelings}"

        if directive:
            system_prompt += f"\n\nRIGHT NOW\n{directive}"

        reply = await self.engine.generate_reply(
            system_prompt,
            label_messages(unsummarized, speaker.id, names, user_name),
        )
        return self._without_own_name(reply, speaker.name)

    async def _relationships_by_name(self, user_id, speaker, members) -> dict:
        others = {m.id: m.name for m in members if m.id != speaker.id}
        rows = await CharacterRelationshipService(self.session).get_for_speaker(
            user_id, speaker.id, list(others)
        )
        return {others[other_id]: row for other_id, row in rows.items()}

    @staticmethod
    def _without_own_name(reply: str, name: str) -> str:
        """Models often start with "Name: ..." because the history is labelled
        that way; the chat already shows who is speaking."""
        for prefix in (f"{name}:", f"**{name}:**", f"**{name}**:"):
            if reply.startswith(prefix):
                return reply[len(prefix):].lstrip() or reply
        return reply

    @staticmethod
    def _last_character_speaker(messages):
        for message in reversed(messages):
            if message.sender_type == "character":
                return message.sender_character_id
        return None

    async def _messages(self, conversation_id):
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        return result.scalars().all()

    async def _load(self, conversation_id, user_id):
        conversation = (
            await self.session.execute(
                select(Conversation)
                .options(
                    selectinload(Conversation.participants).selectinload(
                        ConversationParticipant.character
                    )
                )
                .where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                    Conversation.conversation_type == "group",
                )
            )
        ).scalar_one_or_none()

        if conversation is None:
            raise ValueError("Grup bulunamadı.")

        characters: list[Character] = sorted(
            (p.character for p in conversation.participants),
            key=lambda c: (c.sort_order, c.name),
        )

        if len(characters) < 2 or not all(c.is_active for c in characters):
            raise ValueError("Grup kullanılamıyor.")

        members = []
        for character in characters:
            presented = self.gallery.present(character)
            members.append(
                GroupMember(
                    id=character.id,
                    slug=character.slug,
                    name=presented.name,
                    description=presented.description,
                )
            )

        user = await self.session.get(User, user_id)
        user_name = (user.display_name if user and user.display_name else DEFAULT_USER_NAME)

        return conversation, members, user_name
