from openai import AsyncOpenAI

from app.core.config import settings
from app.providers.base import AIProvider


class GroqProvider(AIProvider):

    def __init__(self, model: str | None = None):
        if not settings.GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to your .env file."
            )

        # An explicit model wins over GROQ_MODEL (handy for A/B testing).
        self.model = model or settings.GROQ_MODEL

        self.client = AsyncOpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            max_retries=settings.AI_MAX_RETRIES,
        )

    async def generate_response(
        self,
        system_prompt: str,
        messages: list[dict],
    ) -> str:

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                *messages,
            ],
            temperature=0.8,
            max_completion_tokens=1000,
        )

        return response.choices[0].message.content or ""
