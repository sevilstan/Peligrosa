import asyncio
from uuid import UUID

from app.database.session import SessionLocal
from app.services.memory_extractor import MemoryExtractor
from app.services.memory_service import MemoryService


async def main():
    user_id = UUID("63a7b31d-e1b3-4528-9c8c-3555e8f1e32f")

    user_message = (
        "Bilim kurgu filmlerine bayılıyorum. "
        "Özellikle Interstellar favorim. "
        "Boş zamanlarımda gitar çalmayı seviyorum."
    )

    # 1. Mesajdan hafıza çıkar
    extractor = MemoryExtractor()

    extracted_memories = await extractor.extract(user_message)

    print("\n--- ÇIKARILAN HAFIZALAR ---")

    if not extracted_memories:
        print("Kaydedilecek hafıza bulunamadı.")
        return

    for item in extracted_memories:
        print(f"[{item['category']}] {item['content']}")

    # 2. Hafızaları veritabanına kaydet
    async with SessionLocal() as session:
        memory_service = MemoryService(session)

        for item in extracted_memories:
            await memory_service.add_memory(
                user_id=user_id,
                category=item["category"],
                content=item["content"],
                importance=item["importance"],
                confidence=item["confidence"],
            )

        print("\n--- VERİTABANINDAN OKUNAN HAFIZALAR ---")

        # 3. Hafızaları tekrar getir
        saved_memories = await memory_service.get_memories(user_id)

        for memory in saved_memories:
            print(
                f"[{memory.category}] "
                f"{memory.content} "
                f"(Önem: {memory.importance})"
            )

        print(f"\nToplam kayıtlı hafıza: " f"{len(saved_memories)}")


if __name__ == "__main__":
    asyncio.run(main())
