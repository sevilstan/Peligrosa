from gettext import translation
import json
import re

from app.models import message
from app.providers.groq_provider import GroqProvider


class MemoryExtractor:
    ALLOWED_CATEGORIES = {
        "interest",
        "preference",
        "personal",
        "goal",
        "hobby",
        "event",
        "relationship",
    }

    ALLOWED_OPERATIONS = {
        "upsert",
        "delete",
    }

    MEMORY_KEY_PATTERN = re.compile(r"^[a-z0-9_]{1,100}$")

    NEGATED_DELETE_PATTERNS = [
    r"\bsilme\b",
    r"\bsilmeyin\b",
    r"\bsilmeni istemiyorum\b",
    r"\bsilmeni istemem\b",
    r"\bdont delete\b",
    r"\bdo not delete\b",
    r"\bdont remove\b",
    r"\bdo not remove\b",
    r"\bdont forget\b",
    r"\bdo not forget\b",
    ]

    DELETE_PATTERNS = [
    r"\bhafizandan sil\b",
    r"\bhafizandan cikar\b",
    r"\bbilgiyi sil\b",
    r"\bbunu sil\b",
    r"\bsilmeni istiyorum\b",
    r"\bsiler misin\b",
    r"\bsilebilir misin\b",
    r"\bforget\b",
    r"\bdelete\b",
    r"\bremove\b",
    ]
    
    def __init__(self, ai_provider=None):
        self.ai_provider = ai_provider or GroqProvider()

    @classmethod
    def is_explicit_deletion_request(cls, message: str) -> bool:
        normalized = message.casefold()

        translation = str.maketrans({
        "ı": "i",
        "ş": "s",
        "ğ": "g",
        "ç": "c",
        "ö": "o",
        "ü": "u",
        })

        normalized = normalized.translate(translation)

    # Farklı apostrof karakterlerini standartlaştır.
        normalized = re.sub(r"['’`]", "", normalized)

    # Olumsuz ifadeler önce kontrol edilir.
        if any(
            re.search(pattern, normalized)
            for pattern in cls.NEGATED_DELETE_PATTERNS
        ):
            return False

        return any(
            re.search(pattern, normalized)
            for pattern in cls.DELETE_PATTERNS
        )

    async def extract(self, user_message: str) -> list[dict]:
        system_prompt = """
You are a long-term memory extraction system for an AI companion.

Extract ONLY stable, explicitly stated facts about the user that
will likely remain useful in future conversations.

Return ONLY valid JSON using this structure:

{
  "memories": [
    {
      "operation": "upsert",
      "memory_key": "favorite_movie",
      "category": "interest",
      "content": "The user's favorite movie is Interstellar.",
      "importance": 8,
      "confidence": 0.95,
      "is_long_term": true
    }
  ]
}

OPERATIONS:

1. upsert:
Create a new memory or update an existing memory with the same key.

2. delete:
Delete an existing memory only when the user explicitly asks
to forget, delete, or remove that information.

A correction or change of preference is NOT a deletion request.

Examples:

"I no longer like Interstellar."
This is NOT a deletion request. Update the existing fact if appropriate.

"Forget that Interstellar is my favorite movie."
This IS a deletion request.

"Interstellar is no longer my favorite movie."
This is NOT a deletion request.

"Interstellar hakkındaki hafızanı sil."
This IS a deletion request.

"Artık Interstellar favorim değil."
This is NOT a deletion request.

MEMORY KEY RULES:

- Keys must be stable semantic identifiers.
- Use lowercase English words separated by underscores.
- Never include the actual memory value in the key.
- Use the SAME key when the same fact is corrected or updated.
- Use different keys for different facts.
- Do not merge related but distinct facts.

Examples:

"The user's favorite movie is Interstellar."
memory_key: favorite_movie

"Interstellar is my favorite film."
memory_key: favorite_movie

"My new favorite movie is Inception."
memory_key: favorite_movie

"I enjoy science fiction movies."
memory_key: interest_science_fiction

"I play guitar."
memory_key: hobby_guitar

"My goal is to learn Spanish."
memory_key: goal_learn_spanish

IMPORTANT:
A general interest in science fiction and a favorite movie are
different facts. Never store them under the same key.

ALLOWED CATEGORIES:
- interest
- preference
- personal
- goal
- hobby
- event: a SIGNIFICANT thing that happened in the user's life or to
  someone close to them, stated by the user (a new job, a move, an exam
  result, a breakup, a birth). Not daily routines, plans or moods.
- relationship: an important person in the user's life and who they are
  to the user ("Osman is my brother", "my manager Aylin").

Examples for the new categories:

"Osman got a new job last week."
memory_key: event_osman_new_job, category: event

"Osman is my older brother."
memory_key: relationship_osman, category: relationship

STRICT RULES:

1. Extract only facts explicitly stated by the user.
2. Save only stable information useful in future conversations.
3. Do not save temporary intentions, moods, activities or situations.
4. Weather, daily plans and momentary feelings are NOT memories.
   (Significant life events and important people ARE: see the event
   and relationship categories.)
5. Do not convert a temporary intention into a permanent preference.
6. Do not invent or infer personal information.
7. Ignore fictional roleplay statements and fictional character facts.
8. Never extract passwords, credentials or identifying secrets.
9. Never extract sensitive personal information such as health,
   religion, political views or sexual orientation.
10. Set is_long_term to true only for clearly stable facts.
11. If uncertain, do not extract anything.
12. Never create a delete operation without an explicit user request.

For upsert, include all fields in the example structure.
For delete, include operation, memory_key and confidence.

If no valid memory action exists, return:
{"memories": []}
"""

        response = await self.ai_provider.generate_response(
            system_prompt=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": user_message,
                }
            ],
        )

        cleaned = response.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return []

        if not isinstance(data, dict):
            return []

        raw_memories = data.get("memories", [])

        if not isinstance(raw_memories, list):
            return []

        memories = []

        for item in raw_memories:
            if not isinstance(item, dict):
                continue

            operation = item.get("operation")
            memory_key = item.get("memory_key")
            confidence = item.get("confidence")

            if operation not in self.ALLOWED_OPERATIONS:
                continue

            if not isinstance(memory_key, str):
                continue

            memory_key = memory_key.strip()

            if not self.MEMORY_KEY_PATTERN.fullmatch(memory_key):
                continue

            if type(confidence) not in (int, float):
                continue

            if not 0 <= confidence <= 1:
                continue

            if operation == "delete":
                if confidence < 0.85:
                    continue

                if not self.is_explicit_deletion_request(user_message):
                    continue

                memories.append({
                    "operation": "delete",
                    "memory_key": memory_key,
                    "confidence": float(confidence),
                })
                continue

            category = item.get("category")
            content = item.get("content")
            importance = item.get("importance")
            is_long_term = item.get("is_long_term")

            if category not in self.ALLOWED_CATEGORIES:
                continue

            if not isinstance(content, str) or not content.strip():
                continue

            if type(importance) is not int or not 1 <= importance <= 10:
                continue

            if confidence < 0.75:
                continue

            if is_long_term is not True:
                continue

            memories.append({
                "operation": "upsert",
                "memory_key": memory_key,
                "category": category,
                "content": content.strip(),
                "importance": importance,
                "confidence": float(confidence),
            })

        return memories
