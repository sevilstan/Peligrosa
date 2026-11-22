import asyncio
from uuid import UUID

from app.database.session import SessionLocal
from app.services.conversation_service import ConversationService
from app.services.character_memory_service import CharacterMemoryService


USER_ID = UUID("63a7b31d-e1b3-4528-9c8c-3555e8f1e32f")
CONVERSATION_ID = UUID("f2219613-c22d-4528-8f65-a837bd95456e")


class FakeAIProvider:
    def __init__(self):
        self.last_system_prompt = ""

    async def generate_response(self, system_prompt, messages):
        if "long-term memory extraction system" in system_prompt.lower():
            return """
            {
                "memories": [
                    {
                        "operation": "upsert",
                        "memory_key": "interest_science_fiction",
                        "category": "interest",
                        "content": "The user enjoys science fiction movies.",
                        "importance": 8,
                        "confidence": 0.95,
                        "is_long_term": true
                    },
                    {
                        "operation": "upsert",
                        "memory_key": "favorite_movie",
                        "category": "interest",
                        "content": "Interstellar is the user's favorite movie.",
                        "importance": 9,
                        "confidence": 0.98,
                        "is_long_term": true
                    }
                ]
            }
            """

        self.last_system_prompt = system_prompt
        return "Seni dinliyorum. Bunu hatırlayacağım."


async def main():
    fake_ai = FakeAIProvider()

    async with SessionLocal() as session:
        service = ConversationService(
            session=session,
            ai_provider=fake_ai,
        )

        print("\n1. Kullanıcı mesajı gönderiliyor...")

        response = await service.send_message(
            conversation_id=CONVERSATION_ID,
            user_id=USER_ID,
            content="Bilim kurgu filmlerini çok seviyorum. Özellikle Interstellar benim favorim.",
        )

        print("AI cevabı:", response.content)

        memory_service = CharacterMemoryService(session)

        memories = await memory_service.get_memories(
            user_id=USER_ID,
            character_id=response.sender_character_id,
        )

        print("\n2. Elena'nın hafızaları:")

        for memory in memories:
            print(
                f"- [{memory.memory_key}] "
                f"[{memory.category}] {memory.content}"
            )

        favorite_movie = next(
            (
                memory for memory in memories
                if memory.memory_key == "favorite_movie"
            ),
            None,
        )

        science_fiction = next(
            (
                memory for memory in memories
                if memory.memory_key == "interest_science_fiction"
            ),
            None,
        )

        assert favorite_movie is not None, "favorite_movie kaydedilmedi!"
        assert science_fiction is not None, "science_fiction hafızası kaydedilmedi!"

        print("\n3. Hafıza sonraki AI isteğine aktarılıyor?")

        assert "CHARACTER'S LONG-TERM MEMORIES ABOUT THE USER" in fake_ai.last_system_prompt
        assert "Interstellar" in fake_ai.last_system_prompt
        assert "science fiction" in fake_ai.last_system_prompt.lower()

        print("Hafızalar system prompt içinde bulundu!")
        print("\nCONVERSATION MEMORY TEST PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
