from dataclasses import dataclass

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.character_emotion import CharacterEmotion
from app.models.character_memory import CharacterMemory
from app.models.character_relationship import CharacterRelationship
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.services.character_gallery_service import CharacterGalleryService, GalleryCharacter
from app.services.chat_session_service import GROUP_MIN_CHARACTERS


class CharacterNotFoundError(Exception):
    """No such character (inactive ones are allowed: users may clean up)."""


@dataclass(frozen=True)
class RemovalSummary:
    character: GalleryCharacter
    direct_chats: int  # direct chats with the character (deleted)
    memories: int  # what the character remembers about this user (deleted)
    groups: int  # groups the character leaves
    groups_deleted: int  # of those, groups left with too few characters

    @property
    def is_empty(self) -> bool:
        return not (self.direct_chats or self.memories or self.groups)


class CharacterRemovalService:
    """Lets a user "delete" a character from THEIR side.

    The character itself is platform-managed and stays in the gallery; what
    goes is everything between this user and the character:
    - their direct chats with it (messages included);
    - the memories it holds about them (user_id + character_id), its mood and
      its relationships with other characters (both directions);
    - its place in their groups. A group left with fewer than 2 characters
      is deleted; other groups, and other characters' memories, are kept.

    Everything is scoped by user_id and done in ONE transaction.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.gallery = CharacterGalleryService(session)

    async def preview(self, user_id, slug: str) -> RemovalSummary:
        character = await self._character(slug)
        direct_ids = await self._direct_chat_ids(user_id, character.id)
        group_ids = await self._group_ids(user_id, character.id)
        doomed = await self._groups_left_too_small(group_ids)

        return RemovalSummary(
            character=self.gallery.present(character),
            direct_chats=len(direct_ids),
            memories=await self._memory_count(user_id, character.id),
            groups=len(group_ids),
            groups_deleted=len(doomed),
        )

    async def remove(self, user_id, slug: str) -> RemovalSummary:
        summary = await self.preview(user_id, slug)
        character = await self._character(slug)

        direct_ids = await self._direct_chat_ids(user_id, character.id)
        group_ids = await self._group_ids(user_id, character.id)
        doomed = await self._groups_left_too_small(group_ids)

        try:
            # Conversations first: messages and participants go with them
            # (ON DELETE CASCADE).
            if direct_ids or doomed:
                await self.session.execute(
                    delete(Conversation).where(
                        Conversation.user_id == user_id,
                        Conversation.id.in_([*direct_ids, *doomed]),
                    )
                )

            staying = [g for g in group_ids if g not in set(doomed)]
            if staying:
                await self.session.execute(
                    delete(ConversationParticipant).where(
                        ConversationParticipant.character_id == character.id,
                        ConversationParticipant.conversation_id.in_(staying),
                    )
                )

            await self.session.execute(
                delete(CharacterMemory).where(
                    CharacterMemory.user_id == user_id,
                    CharacterMemory.character_id == character.id,
                )
            )

            # Its feelings for this user's world, in both directions: what it
            # feels about others and what the others feel about it.
            await self.session.execute(
                delete(CharacterRelationship).where(
                    CharacterRelationship.user_id == user_id,
                    or_(
                        CharacterRelationship.character_id == character.id,
                        CharacterRelationship.other_character_id == character.id,
                    ),
                )
            )
            await self.session.execute(
                delete(CharacterEmotion).where(
                    CharacterEmotion.user_id == user_id,
                    CharacterEmotion.character_id == character.id,
                )
            )

            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return summary

    # ------------------------------------------------------------ internals

    async def _character(self, slug: str) -> Character:
        character = (
            await self.session.execute(select(Character).where(Character.slug == slug))
        ).scalar_one_or_none()

        if character is None:
            raise CharacterNotFoundError()

        return character

    async def _direct_chat_ids(self, user_id, character_id) -> list:
        return list(
            (
                await self.session.execute(
                    select(Conversation.id)
                    .join(
                        ConversationParticipant,
                        ConversationParticipant.conversation_id == Conversation.id,
                    )
                    .where(
                        Conversation.user_id == user_id,
                        Conversation.conversation_type == "direct",
                        ConversationParticipant.character_id == character_id,
                    )
                )
            ).scalars()
        )

    async def _group_ids(self, user_id, character_id) -> list:
        return list(
            (
                await self.session.execute(
                    select(Conversation.id)
                    .join(
                        ConversationParticipant,
                        ConversationParticipant.conversation_id == Conversation.id,
                    )
                    .where(
                        Conversation.user_id == user_id,
                        Conversation.conversation_type == "group",
                        ConversationParticipant.character_id == character_id,
                    )
                )
            ).scalars()
        )

    async def _groups_left_too_small(self, group_ids: list) -> list:
        """Groups that would have fewer than 2 characters without this one."""
        if not group_ids:
            return []

        counts = await self.session.execute(
            select(ConversationParticipant.conversation_id, func.count())
            .where(ConversationParticipant.conversation_id.in_(group_ids))
            .group_by(ConversationParticipant.conversation_id)
        )
        return [cid for cid, members in counts if members - 1 < GROUP_MIN_CHARACTERS]

    async def _memory_count(self, user_id, character_id) -> int:
        return (
            await self.session.execute(
                select(func.count())
                .select_from(CharacterMemory)
                .where(
                    CharacterMemory.user_id == user_id,
                    CharacterMemory.character_id == character_id,
                )
            )
        ).scalar_one()
