import asyncio
from uuid import UUID

from app.database.session import SessionLocal
from app.services.conversation_service import ConversationService


async def main():
    conversation_id = UUID("f2219613-c22d-4528-8f65-a837bd95456e")

    user_id = UUID("63a7b31d-e1b3-4528-9c8c-3555e8f1e32f")

    async with SessionLocal() as session:
        service = ConversationService(session)

        print("\nKullanıcı: Merhaba Elena! Beni hatırlıyor musun?")

        response = await service.send_message(
            conversation_id=conversation_id,
            user_id=user_id,
            content="Merhaba Elena! Beni hatırlıyor musun?",
        )

        print(f"\nElena: {response.content}")

        print("\n--- KONUŞMA GEÇMİŞİ ---")

        history = await service.get_conversation_history(
            conversation_id=conversation_id,
            user_id=user_id,
        )

        for message in history:
            print(f"{message.sender_type}: {message.content}")

        print(f"\nToplam mesaj: {len(history)}")


if __name__ == "__main__":
    asyncio.run(main())
