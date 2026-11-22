from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_memory import UserMemory


class MemoryService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_memory(
        self,
        user_id: UUID,
        category: str,
        content: str,
        importance: int = 5,
        confidence: float = 0.8,
    ):
        content = content.strip()
        category = category.strip().lower()

        if not content:
            raise ValueError("Hafıza içeriği boş olamaz.")

        if not category:
            raise ValueError("Hafıza kategorisi boş olamaz.")

        if not 1 <= importance <= 10:
            raise ValueError("Önem derecesi 1-10 arasında olmalı.")

        if not 0 <= confidence <= 1:
            raise ValueError("Güven seviyesi 0-1 arasında olmalı.")

        result = await self.session.execute(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.category == category,
                UserMemory.content == content,
            )
        )

        memory = result.scalar_one_or_none()

        if memory:
            memory.importance = importance
            memory.confidence = confidence
        else:
            memory = UserMemory(
                user_id=user_id,
                category=category,
                content=content,
                importance=importance,
                confidence=confidence,
            )
            self.session.add(memory)

        await self.session.commit()
        await self.session.refresh(memory)

        return memory

    async def get_memories(self, user_id: UUID):
        result = await self.session.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(
                UserMemory.importance.desc(),
                UserMemory.updated_at.desc(),
            )
        )

        return result.scalars().all()

    async def update_memory(
        self,
        memory_id: UUID,
        user_id: UUID,
        content: str,
        importance: int,
        confidence: float,
    ):
        if not content.strip():
            raise ValueError("Hafıza içeriği boş olamaz.")

        if not 1 <= importance <= 10:
            raise ValueError("Önem derecesi 1-10 arasında olmalı.")

        if not 0 <= confidence <= 1:
            raise ValueError("Güven seviyesi 0-1 arasında olmalı.")

        result = await self.session.execute(
            select(UserMemory).where(
                UserMemory.id == memory_id,
                UserMemory.user_id == user_id,
            )
        )

        memory = result.scalar_one_or_none()

        if memory is None:
            return None

        memory.content = content.strip()
        memory.importance = importance
        memory.confidence = confidence

        await self.session.commit()
        await self.session.refresh(memory)

        return memory

    async def delete_memory(
        self,
        memory_id: UUID,
        user_id: UUID,
    ):
        result = await self.session.execute(
            select(UserMemory).where(
                UserMemory.id == memory_id,
                UserMemory.user_id == user_id,
            )
        )

        memory = result.scalar_one_or_none()

        if memory is None:
            return False

        await self.session.delete(memory)
        await self.session.commit()

        return True
