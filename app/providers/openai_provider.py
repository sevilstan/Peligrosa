from openai import AsyncOpenAI

from app.core.config import settings
from app.providers.base import AIProvider


class OpenAIProvider(AIProvider):

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

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
