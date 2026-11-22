import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.database.session import SessionLocal
from app.models.user import User
from app.models.character import Character
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.models.message import Message
from app.services.conversation_service import ConversationService


async def main():
    async with SessionLocal() as session:

        service = ConversationService(session)

        conversation_id = "f2219613-c22d-4528-8f65-a837bd95456e"
        user_id = "63a7b31d-e1b3-4528-9c8c-3555e8f1e32f"

        messages = await service.get_conversation_history(
            conversation_id=conversation_id,
            user_id=user_id,
        )

        print("\n--- KONUŞMA GEÇMİŞİ ---")

        for message in messages:
            print(f"{message.sender_type}: {message.content}")

        print(f"\nToplam mesaj: {len(messages)}")


if __name__ == "__main__":
    asyncio.run(main())
