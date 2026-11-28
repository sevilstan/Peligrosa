import uuid
from dataclasses import dataclass

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.character import Character
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.models.message import Message
from app.services.character_gallery_service import (
    CharacterGalleryService,
    GalleryCharacter,
)
from app.services.conversation_service import ConversationService

CHAT_PAGE_SIZE = 5
HISTORY_PAGE_SIZE = 8
GROUP_MIN_CHARACTERS = 2
GROUP_MAX_CHARACTERS = 4
_TITLE_LIMIT = 200
RENAME_LIMIT = 40


class ChatNotAvailableError(Exception):
    """The character or conversation does not exist, is inactive, or is not
    the user's. Deliberately one error for all cases (no information leak)."""


class InvalidGroupError(Exception):
    """The chosen characters cannot form a group.

    reason: "too_few", "too_many" or "unavailable" (unknown, inactive or
    repeated characters).
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Members:
    """Shared by every view of a conversation: who is in it."""

    characters: tuple[GalleryCharacter, ...]
    title: str | None

    @property
    def is_group(self) -> bool:
        return len(self.characters) > 1

    @property
    def character(self) -> GalleryCharacter:
        """The one character of a direct chat (the first member of a group)."""
        return self.characters[0]

    @property
    def name(self) -> str:
        if self.is_group:
            return self.title or ", ".join(c.name for c in self.characters)
        return self.characters[0].name

    @property
    def label(self) -> str:
        """What the chat is called in lists: its title, plus who it is with."""
        # New direct chats are titled with the character's name: not a custom title.
        if self.is_group or not self.title or self.title == self.name:
            return self.name
        return f"{self.title} · {self.name}"


def clean_title(raw: str | None) -> str | None:
    """A chat title the user typed: one line, no control characters, <= 40
    characters. None when nothing usable is left."""
    text = "".join(" " if ch.isspace() else ch for ch in (raw or "") if ch.isprintable() or ch.isspace())
    text = " ".join(text.split())
    return text[:RENAME_LIMIT].strip() or None


@dataclass(frozen=True)
class ChatContext(_Members):
    conversation_id: uuid.UUID
    characters: tuple[GalleryCharacter, ...]
    created: bool = False
    title: str | None = None


@dataclass(frozen=True)
class ChatSummary(_Members):
    conversation_id: uuid.UUID
    characters: tuple[GalleryCharacter, ...]
    created_at: object
    is_active: bool
    title: str | None = None


@dataclass(frozen=True)
class ChatListPage:
    items: list[ChatSummary]
    page: int  # zero-based, clamped into range
    total_pages: int


@dataclass(frozen=True)
class HistoryMessage:
    from_user: bool
    content: str
    # Who spoke, for character messages in a group (None in direct chats).
    speaker: str | None = None


@dataclass(frozen=True)
class HistoryPage(_Members):
    characters: tuple[GalleryCharacter, ...]
    messages: list[HistoryMessage]  # oldest first within the page
    page: int  # 0 = the newest messages
    total_pages: int
    title: str | None = None


class ChatSessionService:
    """Which conversation a user is talking in, and moving between them.

    A chat is a direct conversation (one character) or a persistent group
    (several characters). The ACTIVE chat is the user's conversation with the
    newest updated_at. Opening or switching to a chat "touches" it; sending messages
    does not change it, and neither does the background summary. This needs
    no extra column: Telegram plain text has no chat attached, so "the chat
    the user last opened" is what a message belongs to.

    Every query is scoped by user_id. A chat is only available while ALL of
    its characters are active.
    """

    def __init__(self, session: AsyncSession, ai_provider=None):
        self.session = session
        self.ai_provider = ai_provider
        self.gallery = CharacterGalleryService(session)

    async def open_character_chat(self, user_id, slug: str) -> ChatContext:
        """Continue the latest direct chat with this character, or start one."""
        character = await self._active_character(slug)

        conversation = (
            await self.session.execute(
                self._conversations(user_id)
                .where(
                    Conversation.conversation_type == "direct",
                    Conversation.participants.any(
                        ConversationParticipant.character_id == character.id
                    ),
                )
                .limit(1)
            )
        ).scalars().first()

        if conversation is not None:
            await self._touch(conversation.id, user_id)
            return self._context(conversation, created=False)

        return await self._create(user_id, character)

    async def start_new_chat(self, user_id, slug: str) -> ChatContext:
        character = await self._active_character(slug)
        return await self._create(user_id, character)

    async def create_group(self, user_id, slugs: list[str]) -> ChatContext:
        """A persistent group chat with 2-4 distinct, active characters."""
        slugs = list(dict.fromkeys(slugs))  # drop repeats, keep the order

        if len(slugs) < GROUP_MIN_CHARACTERS:
            raise InvalidGroupError("too_few")
        if len(slugs) > GROUP_MAX_CHARACTERS:
            raise InvalidGroupError("too_many")

        characters = (
            await self.session.execute(
                select(Character).where(
                    Character.slug.in_(slugs),
                    Character.is_active.is_(True),
                )
            )
        ).scalars().all()

        if len(characters) != len(slugs):
            raise InvalidGroupError("unavailable")

        by_slug = {c.slug: c for c in characters}
        ordered = [by_slug[slug] for slug in slugs]
        names = ", ".join(self.gallery.present(c).name for c in ordered)

        conversation = Conversation(
            user_id=user_id,
            title=names[:_TITLE_LIMIT],
            conversation_type="group",
        )
        conversation.participants.extend(
            ConversationParticipant(character=c) for c in ordered
        )
        self.session.add(conversation)
        await self.session.commit()

        await self._touch(conversation.id, user_id)
        return ChatContext(
            conversation_id=conversation.id,
            characters=tuple(self.gallery.present(c) for c in ordered),
            created=True,
            title=conversation.title,
        )

    async def switch_to(self, user_id, conversation_id) -> ChatContext:
        conversation = await self._one(user_id, conversation_id)
        await self._touch(conversation.id, user_id)
        return self._context(conversation, created=False)

    async def rename(self, user_id, conversation_id, raw: str | None) -> ChatContext:
        """Give a chat a title. Empty/unusable text resets a direct chat's
        title; a group falls back to its member names."""
        conversation = await self._one(user_id, conversation_id)
        title = clean_title(raw)
        # updated_at is kept as is: renaming must not reorder the chat list.
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(title=title, updated_at=Conversation.updated_at)
        )
        await self.session.commit()
        await self.session.refresh(conversation)
        return self._context(conversation, created=False)

    async def get_active(self, user_id) -> ChatContext | None:
        conversation = (
            await self.session.execute(self._conversations(user_id).limit(1))
        ).scalars().first()

        return self._context(conversation, created=False) if conversation else None

    async def list_chats(
        self, user_id, page: int = 0, page_size: int = CHAT_PAGE_SIZE
    ) -> ChatListPage:
        """The user's chats, the active one first. Pages are clamped."""
        total = (
            await self.session.execute(
                select(func.count())
                .select_from(Conversation)
                .where(*self._clauses(user_id))
            )
        ).scalar_one()

        total_pages = max(1, -(-total // page_size))
        page = min(max(page, 0), total_pages - 1)

        conversations = (
            await self.session.execute(
                self._conversations(user_id).limit(page_size).offset(page * page_size)
            )
        ).scalars().all()

        return ChatListPage(
            items=[
                ChatSummary(
                    conversation_id=conversation.id,
                    characters=self._members(conversation),
                    created_at=conversation.created_at,
                    is_active=page == 0 and index == 0,
                    title=conversation.title,
                )
                for index, conversation in enumerate(conversations)
            ],
            page=page,
            total_pages=total_pages,
        )

    async def get_history(
        self,
        user_id,
        conversation_id,
        page: int = 0,
        page_size: int = HISTORY_PAGE_SIZE,
    ) -> HistoryPage:
        """Messages of one of the user's chats; page 0 is the newest."""
        conversation = await self._one(user_id, conversation_id)

        total = (
            await self.session.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation_id)
            )
        ).scalar_one()

        total_pages = max(1, -(-total // page_size))
        page = min(max(page, 0), total_pages - 1)

        messages = (
            await self.session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(page_size)
                .offset(page * page_size)
            )
        ).scalars().all()

        speaker_names = (
            {
                p.character_id: self.gallery.present(p.character).name
                for p in conversation.participants
            }
            if conversation.conversation_type == "group"
            else {}
        )

        return HistoryPage(
            characters=self._members(conversation),
            title=conversation.title,
            messages=[
                HistoryMessage(
                    from_user=m.sender_type == "user",
                    content=m.content,
                    speaker=speaker_names.get(m.sender_character_id),
                )
                for m in reversed(messages)
            ],
            page=page,
            total_pages=total_pages,
        )

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
    def _clauses(user_id) -> list:
        """The user's direct chats and groups whose characters are ALL active."""
        has_inactive_member = exists().where(
            ConversationParticipant.conversation_id == Conversation.id,
            ConversationParticipant.character_id == Character.id,
            Character.is_active.is_(False),
        )
        has_member = exists().where(
            ConversationParticipant.conversation_id == Conversation.id
        )
        return [
            Conversation.user_id == user_id,
            Conversation.conversation_type.in_(("direct", "group")),
            has_member,
            ~has_inactive_member,
        ]

    def _conversations(self, user_id):
        """Newest-opened first, with their characters loaded."""
        return (
            select(Conversation)
            .options(
                selectinload(Conversation.participants).selectinload(
                    ConversationParticipant.character
                )
            )
            .where(*self._clauses(user_id))
            .order_by(
                Conversation.updated_at.desc(),
                Conversation.created_at.desc(),
                Conversation.id,
            )
        )

    async def _one(self, user_id, conversation_id) -> Conversation:
        conversation = (
            await self.session.execute(
                self._conversations(user_id).where(Conversation.id == conversation_id)
            )
        ).scalars().first()

        if conversation is None:
            raise ChatNotAvailableError()

        return conversation

    def _members(self, conversation: Conversation) -> tuple[GalleryCharacter, ...]:
        characters = sorted(
            (p.character for p in conversation.participants),
            key=lambda c: (c.sort_order, c.name),
        )
        return tuple(self.gallery.present(c) for c in characters)

    def _context(self, conversation: Conversation, created: bool) -> ChatContext:
        return ChatContext(
            conversation_id=conversation.id,
            characters=self._members(conversation),
            created=created,
            title=conversation.title,
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
        return ChatContext(conversation.id, (self.gallery.present(character),), True)

    async def _touch(self, conversation_id, user_id) -> None:
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .values(updated_at=func.clock_timestamp())
            .execution_options(synchronize_session=False)
        )
        await self.session.commit()
