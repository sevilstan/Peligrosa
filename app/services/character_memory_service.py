import re
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character_memory import CharacterMemory


# Words too common to say anything about the topic (English and Turkish).
_STOP_WORDS = frozenset(
    """
    this that with have what your about from they were been will would there
    their when where which user just like very more some than then them
    bunu şunu için gibi kadar değil nasıl neden çok daha ama fakat ancak
    bence sence şey şeyi
    """.split()
)
_MIN_TERM_LENGTH = 4
_MAX_TERMS = 8
_STEM_LENGTH = 5


def topic_terms(text: str | None) -> list[str]:
    """Words of a message worth matching against memories.

    Crude on purpose (no language models, no embeddings): lowercase letters
    only, stop words removed, longest words first, plus a short stem of long
    words so "filmleri" can find a memory that says "film".
    """
    if not text:
        return []

    words = re.findall(r"[^\W\d_]+", text.lower())
    unique = dict.fromkeys(w for w in words if len(w) >= _MIN_TERM_LENGTH and w not in _STOP_WORDS)
    chosen = sorted(unique, key=len, reverse=True)[:_MAX_TERMS]

    terms = list(chosen)
    for word in chosen:
        if len(word) > _STEM_LENGTH + 1 and word[:_STEM_LENGTH] not in terms:
            terms.append(word[:_STEM_LENGTH])
    return terms


class CharacterMemoryService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_memory(
        self,
        user_id: uuid.UUID,
        character_id: uuid.UUID,
        category: str,
        content: str,
        importance: int = 5,
        confidence: float = 0.8,
        memory_key: str | None = None,
        source_conversation_id: uuid.UUID | None = None,
        source_kind: str | None = None,
    ) -> CharacterMemory | None:

        content = content.strip()

        if not content:
            return None

        if memory_key is not None:
            memory_key = memory_key.strip() or None

        base_conditions = [
            CharacterMemory.user_id == user_id,
            CharacterMemory.character_id == character_id,
        ]

        memory = None

        # 1. Önce memory_key üzerinden mevcut kaydı ara.
        if memory_key is not None:
            result = await self.session.execute(
                select(CharacterMemory).where(
                    *base_conditions,
                    CharacterMemory.memory_key == memory_key,
                )
            )
            memory = result.scalar_one_or_none()

        # 2. Bulunamazsa eski, memory_key alanı NULL olan kaydı ara.
        if memory is None:
            result = await self.session.execute(
                select(CharacterMemory).where(
                    *base_conditions,
                    CharacterMemory.category == category,
                    CharacterMemory.content == content,
                    CharacterMemory.memory_key.is_(None),
                )
            )
            memory = result.scalar_one_or_none()

        # 3. Mevcut kaydı güncelle veya yeni kayıt oluştur.
        if memory:
            memory.category = category
            memory.content = content
            memory.memory_key = memory_key
            memory.importance = importance
            memory.confidence = confidence
            if source_kind is not None:
                # The latest place it was told in.
                memory.source_conversation_id = source_conversation_id
                memory.source_kind = source_kind
        else:
            memory = CharacterMemory(
                user_id=user_id,
                character_id=character_id,
                category=category,
                content=content,
                memory_key=memory_key,
                importance=importance,
                confidence=confidence,
                source_conversation_id=source_conversation_id,
                source_kind=source_kind,
            )
            self.session.add(memory)

        await self.session.flush()
        await self.session.refresh(memory)

        return memory

    async def get_memories(
        self,
        user_id: uuid.UUID,
        character_id: uuid.UUID,
        limit: int | None = None,
    ) -> list[CharacterMemory]:

        query = (
            select(CharacterMemory)
            .where(
                CharacterMemory.user_id == user_id,
                CharacterMemory.character_id == character_id,
            )
            .order_by(
                CharacterMemory.importance.desc(),
                CharacterMemory.updated_at.desc(),
            )
        )

        if limit is not None:
            query = query.limit(limit)

        result = await self.session.execute(query)

        return list(result.scalars().all())

    async def delete_memory(
        self,
        memory_id: uuid.UUID,
        user_id: uuid.UUID,
        character_id: uuid.UUID,
    ) -> bool:

        result = await self.session.execute(
            select(CharacterMemory).where(
                CharacterMemory.id == memory_id,
                CharacterMemory.user_id == user_id,
                CharacterMemory.character_id == character_id,
            )
        )

        memory = result.scalar_one_or_none()

        if not memory:
            return False

        await self.session.delete(memory)
        await self.session.flush()

        return True

    async def delete_memory_by_key(
        self,
        user_id: uuid.UUID,
        character_id: uuid.UUID,
        memory_key: str,
    ) -> bool:

        result = await self.session.execute(
            select(CharacterMemory).where(
                CharacterMemory.user_id == user_id,
                CharacterMemory.character_id == character_id,
                CharacterMemory.memory_key == memory_key,
            )
        )

        memory = result.scalar_one_or_none()

        if not memory:
            return False

        await self.session.delete(memory)
        await self.session.flush()

        return True

    async def get_relevant_memories(
        self,
        user_id: uuid.UUID,
        character_id: uuid.UUID,
        context_text: str | None,
        limit: int = 10,
    ) -> list[CharacterMemory]:
        """The memories this character should have in mind right now.

        Half the budget always goes to the most important memories; the rest
        goes first to memories that match what is being talked about, then
        back to importance. The total never exceeds `limit`, so the prompt
        stays the same size however many memories pile up.

        Scoped by user_id AND character_id like every other query here.
        """
        top = await self.get_memories(user_id, character_id, limit=limit)

        terms = topic_terms(context_text)
        if not terms or len(top) < limit:
            # Nothing to match, or everything already fits.
            return top

        base_count = limit // 2
        base = top[:base_count]

        matches = or_(
            *[
                or_(
                    func.lower(CharacterMemory.content).contains(term, autoescape=True),
                    func.lower(func.coalesce(CharacterMemory.memory_key, "")).contains(
                        term, autoescape=True
                    ),
                )
                for term in terms
            ]
        )

        matched = (
            await self.session.execute(
                select(CharacterMemory)
                .where(
                    CharacterMemory.user_id == user_id,
                    CharacterMemory.character_id == character_id,
                    CharacterMemory.id.not_in([m.id for m in base]),
                    matches,
                )
                .order_by(
                    CharacterMemory.importance.desc(),
                    CharacterMemory.updated_at.desc(),
                )
                .limit(limit - base_count)
            )
        ).scalars().all()

        chosen_ids = {m.id for m in [*base, *matched]}
        filler = [m for m in top[base_count:] if m.id not in chosen_ids]

        return [*base, *matched, *filler][:limit]
