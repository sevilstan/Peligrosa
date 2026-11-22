from openai import AsyncOpenAI

from app.core.config import settings
from app.providers.base import AIProvider


class OpenAIProvider(AIProvider):

    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to your .env file."
            )

        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            max_retries=settings.AI_MAX_RETRIES,
        )

    async def generate_response(
        self,
        system_prompt: str,
        messages: list[dict],
    ) -> str:

        response = await self.client.responses.create(
            model=settings.OPENAI_MODEL,
            instructions=system_prompt,
            input=messages,
        )

        return response.output_text
