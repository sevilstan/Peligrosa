import asyncio
from uuid import UUID

from app.database.session import SessionLocal
from app.services.memory_service import MemoryService


async def main():
    user_id = UUID("63a7b31d-e1b3-4528-9c8c-3555e8f1e32f")

    async with SessionLocal() as session:
        memory_service = MemoryService(session)

        # Hafıza kaydet
        memory = await memory_service.add_memory(
            user_id=user_id,
            category="interest",
            content="Bilim kurgu filmlerini çok seviyor.",
            importance=8,
            confidence=0.95,
        )

        print("\n--- KAYDEDİLEN HAFIZA ---")
        print(memory.content)
        print(f"Kategori: {memory.category}")
        print(f"Önem: {memory.importance}")

        # Hafızaları getir
        memories = await memory_service.get_memories(user_id)

        print("\n--- TÜM KULLANICI HAFIZALARI ---")

        for item in memories:
            print(f"[{item.category}] " f"{item.content} " f"(Önem: {item.importance})")

        print(f"\nToplam hafıza: {len(memories)}")


if __name__ == "__main__":
    asyncio.run(main())
