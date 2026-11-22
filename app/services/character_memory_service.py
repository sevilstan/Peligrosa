import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character_memory import CharacterMemory


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
        else:
            memory = CharacterMemory(
                user_id=user_id,
                character_id=character_id,
                category=category,
                content=content,
                memory_key=memory_key,
                importance=importance,
                confidence=confidence,
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
