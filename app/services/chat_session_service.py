import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.models.message import Message
from app.services.character_gallery_service import (
    CharacterGalleryService,
    GalleryCharacter,
)
from app.services.conversation_service import ConversationService

CHAT_LIST_LIMIT = 10


class ChatNotAvailableError(Exception):
    """The character or conversation does not exist, is inactive, or is not
    the user's. Deliberately one error for all cases (no information leak)."""


@dataclass(frozen=True)
class ChatContext:
    conversation_id: uuid.UUID
    character: GalleryCharacter
    created: bool = False


@dataclass(frozen=True)
class ChatSummary:
    conversation_id: uuid.UUID
    character: GalleryCharacter
    created_at: object
    is_active: bool


class ChatSessionService:
    """Which conversation a user is talking in, and moving between them.

    The ACTIVE chat is the user's direct conversation with the newest
    updated_at. Opening or switching to a chat "touches" it; sending messages
    does not change it, and neither does the background summary. This needs
    no extra column: Telegram plain text has no chat attached, so "the chat
    the user last opened" is what a message belongs to.

    Every query is scoped by user_id; characters must be active.
    """

    def __init__(self, session: AsyncSession, ai_provider=None):
        self.session = session
        self.ai_provider = ai_provider
        self.gallery = CharacterGalleryService(session)

    async def open_character_chat(self, user_id, slug: str) -> ChatContext:
        """Continue the latest chat with this character, or start the first."""
        character = await self._active_character(slug)

        row = (
            await self.session.execute(
                self._direct_conversations(user_id)
                .where(Character.id == character.id)
                .limit(1)
            )
        ).first()

        if row is not None:
            conversation = row[0]
            await self._touch(conversation.id, user_id)
            return ChatContext(conversation.id, self.gallery.present(character), False)

        return await self._create(user_id, character)

    async def start_new_chat(self, user_id, slug: str) -> ChatContext:
        character = await self._active_character(slug)
        return await self._create(user_id, character)

    async def switch_to(self, user_id, conversation_id) -> ChatContext:
        row = (
            await self.session.execute(
                self._direct_conversations(user_id)
                .where(Conversation.id == conversation_id)
            )
        ).first()

        if row is None:
            raise ChatNotAvailableError()

        conversation, character = row
        await self._touch(conversation.id, user_id)
        return ChatContext(conversation.id, self.gallery.present(character), False)

    async def get_active(self, user_id) -> ChatContext | None:
        row = (
            await self.session.execute(
                self._direct_conversations(user_id).limit(1)
            )
        ).first()

        if row is None:
            return None

        conversation, character = row
        return ChatContext(conversation.id, self.gallery.present(character), False)

    async def list_chats(self, user_id, limit: int = CHAT_LIST_LIMIT) -> list[ChatSummary]:
        rows = (
            await self.session.execute(
                self._direct_conversations(user_id).limit(limit)
            )
        ).all()

        return [
            ChatSummary(
                conversation_id=conversation.id,
                character=self.gallery.present(character),
                created_at=conversation.created_at,
                is_active=index == 0,
            )
            for index, (conversation, character) in enumerate(rows)
        ]

    async def last_character_message(self, user_id, conversation_id) -> str | None:
        """Latest reply from the character, for a "where we left off" recap."""
        return (
            await self.session.execute(
                select(Message.content)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Message.conversation_id == conversation_id,
                    Conversation.user_id == user_id,
                    Message.sender_type == "character",
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # ------------------------------------------------------------ internals

    @staticmethod
    def _direct_conversations(user_id):
        """The user's direct chats with ACTIVE characters, newest-opened first."""
        return (
            select(Conversation, Character)
            .join(
                ConversationParticipant,
                ConversationParticipant.conversation_id == Conversation.id,
            )
            .join(Character, Character.id == ConversationParticipant.character_id)
            .where(
                Conversation.user_id == user_id,
                Conversation.conversation_type == "direct",
                Character.is_active.is_(True),
            )
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc(), Conversation.id)
        )

    async def _active_character(self, slug: str) -> Character:
        character = (
            await self.session.execute(
                select(Character).where(
                    Character.slug == slug,
                    Character.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

        if character is None:
            raise ChatNotAvailableError()

        return character

    async def _create(self, user_id, character: Character) -> ChatContext:
        conversation = await ConversationService(
            self.session, ai_provider=self.ai_provider
        ).create_conversation(user_id=user_id, character_id=character.id)

        # clock_timestamp() (not now()) so two touches in a row never tie.
        await self._touch(conversation.id, user_id)
        return ChatContext(conversation.id, self.gallery.present(character), True)

    async def _touch(self, conversation_id, user_id) -> None:
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .values(updated_at=func.clock_timestamp())
            .execution_options(synchronize_session=False)
        )
        await self.session.commit()
