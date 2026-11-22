import asyncio
import uuid

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.character import Character
from app.services.character_memory_service import CharacterMemoryService


USER_ID = uuid.UUID("63a7b31d-e1b3-4528-9c8c-3555e8f1e32f")
OTHER_USER_ID = uuid.uuid4()


async def main():
    async with SessionLocal() as session:
        try:
            result = await session.execute(
                select(Character)
                .where(Character.is_active.is_(True))
                .order_by(Character.sort_order)
                .limit(1)
            )

            elena = result.scalar_one_or_none()

            if not elena:
                print("Aktif karakter bulunamadı.")
                return

            service = CharacterMemoryService(session)

            other_character_id = uuid.uuid4()
            memory_key = f"test_memory_{uuid.uuid4().hex[:12]}"

            print(f"\nKarakter: {elena.name}")

            # 1. Yeni hafıza oluştur.
            memory = await service.add_memory(
                user_id=USER_ID,
                character_id=elena.id,
                category="interest",
                content="The user likes science fiction.",
                importance=5,
                confidence=0.80,
                memory_key=memory_key,
            )

            print("\n1. Yeni hafıza oluşturma:")
            print("BAŞARILI" if memory else "BAŞARISIZ")

            # 2. Aynı anahtarla farklı bilgi gönder.
            updated = await service.add_memory(
                user_id=USER_ID,
                character_id=elena.id,
                category="interest",
                content="The user loves science fiction movies.",
                importance=9,
                confidence=0.98,
                memory_key=memory_key,
            )

            print("\n2. Aynı anahtarla hafıza güncelleme:")
            update_passed = (
                updated.id == memory.id
                and updated.content == "The user loves science fiction movies."
                and updated.importance == 9
                and updated.confidence == 0.98
            )
            print("BAŞARILI" if update_passed else "BAŞARISIZ")

            # 3. Aynı anahtar için yalnızca bir kayıt bulunmalı.
            memories = await service.get_memories(USER_ID, elena.id)

            matching = [
                item for item in memories
                if item.memory_key == memory_key
            ]

            print("\n3. Aynı anahtarda mükerrer kayıt oluşmaması:")
            print("BAŞARILI" if len(matching) == 1 else "BAŞARISIZ")

            # 4. Başka karakter hafızayı görememeli.
            other_character_memories = await service.get_memories(
                USER_ID, other_character_id
            )

            character_leak = any(
                item.memory_key == memory_key
                for item in other_character_memories
            )

            print("\n4. Karakter hafıza izolasyonu:")
            print("BAŞARILI" if not character_leak else "BAŞARISIZ")

            # 5. Başka kullanıcı hafızayı görememeli.
            other_user_memories = await service.get_memories(
                OTHER_USER_ID, elena.id
            )

            user_leak = any(
                item.memory_key == memory_key
                for item in other_user_memories
            )

            print("\n5. Kullanıcı hafıza izolasyonu:")
            print("BAŞARILI" if not user_leak else "BAŞARISIZ")

            # 6. Başka kullanıcı hafızayı silememeli.
            wrong_user_delete = await service.delete_memory(
                memory_id=memory.id,
                user_id=OTHER_USER_ID,
                character_id=elena.id,
            )

            print("\n6. Başka kullanıcı hafızayı silemiyor:")
            print("BAŞARILI" if not wrong_user_delete else "BAŞARISIZ")

            # 7. Başka karakter hafızayı silememeli.
            wrong_character_delete = await service.delete_memory(
                memory_id=memory.id,
                user_id=USER_ID,
                character_id=other_character_id,
            )

            print("\n7. Başka karakter hafızayı silemiyor:")
            print("BAŞARILI" if not wrong_character_delete else "BAŞARISIZ")

            # 8. Doğru kullanıcı ve karakter hafızayı silebilmeli.
            deleted = await service.delete_memory_by_key(
                user_id=USER_ID,
                character_id=elena.id,
                memory_key=memory_key,
            )

            print("\n8. Anahtarla hafıza silme:")
            print("BAŞARILI" if deleted else "BAŞARISIZ")

            remaining = await service.get_memories(USER_ID, elena.id)

            still_exists = any(
                item.memory_key == memory_key
                for item in remaining
            )

            print("\n9. Silinen hafıza artık bulunmuyor:")
            print("BAŞARILI" if not still_exists else "BAŞARISIZ")

            checks = [
                memory is not None,
                update_passed,
                len(matching) == 1,
                not character_leak,
                not user_leak,
                not wrong_user_delete,
                not wrong_character_delete,
                deleted,
                not still_exists,
            ]

            print(f"\nSONUÇ: {sum(checks)}/{len(checks)} test başarılı.")

            if all(checks):
                print("ALL CHARACTER MEMORY TESTS PASSED!")
            else:
                print("BAZI TESTLER BAŞARISIZ!")

        finally:
            await session.rollback()
            print("\nTest transaction geri alındı.")


if __name__ == "__main__":
    asyncio.run(main())
