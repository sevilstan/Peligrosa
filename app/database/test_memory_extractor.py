import asyncio

from app.services.memory_extractor import MemoryExtractor


class FakeAIProvider:
    async def generate_response(self, system_prompt, messages):
        return """
        {
            "memories": [
                {
                    "operation": "upsert",
                    "memory_key": "favorite_movie",
                    "category": "interest",
                    "content": "The user's favorite movie is Interstellar.",
                    "importance": 9,
                    "confidence": 0.98,
                    "is_long_term": true
                },
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
                    "operation": "delete",
                    "memory_key": "old_preference",
                    "confidence": 0.98
                },
                {
                    "operation": "upsert",
                    "memory_key": "temporary_mood",
                    "category": "personal",
                    "content": "The user feels tired tonight.",
                    "importance": 5,
                    "confidence": 0.95,
                    "is_long_term": false
                },
                {
                    "operation": "upsert",
                    "memory_key": "INVALID KEY!",
                    "category": "interest",
                    "content": "Invalid key test.",
                    "importance": 5,
                    "confidence": 0.95,
                    "is_long_term": true
                }
            ]
        }
        """


async def main():
    extractor = MemoryExtractor(ai_provider=FakeAIProvider())

    memories = await extractor.extract(
        "I love science fiction. Interstellar is my favorite movie."
    )

    print("\nExtracted memories:")

    for memory in memories:
        print(memory)

    assert len(memories) == 3, "Unexpected memory count!"

    assert memories[0]["memory_key"] == "favorite_movie"
    assert memories[0]["operation"] == "upsert"

    assert memories[1]["memory_key"] == "interest_science_fiction"

    assert memories[2]["operation"] == "delete"
    assert memories[2]["memory_key"] == "old_preference"

    assert all(
        memory["memory_key"] != "temporary_mood"
        for memory in memories
    )

    print("\nALL EXTRACTOR TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
