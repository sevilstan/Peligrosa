import asyncio

from app.core.config import settings
from app.providers.openai_provider import OpenAIProvider


async def main():

    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY bulunamadı. .env dosyasını kontrol et.")

    provider = OpenAIProvider()

    try:
        response = await provider.generate_response(
            system_prompt=(
                "You are Elena, a fictional adult character. "
                "You are witty, warm, confident and mysterious. "
                "Stay in character. Respond in Turkish."
            ),
            messages=[{"role": "user", "content": "Merhaba Elena, bugün nasılsın?"}],
        )

        print("\n--- ELENA'NIN CEVABI ---")
        print(response)

    finally:
        await provider.client.close()


if __name__ == "__main__":
    asyncio.run(main())
