import asyncio

from app.providers.groq_provider import GroqProvider


async def main():
    provider = GroqProvider()

    response = await provider.generate_response(
        system_prompt=(
            "You are Elena, a fictional adult character. "
            "You are warm, natural and expressive. "
            "Stay in character and respond in Turkish."
        ),
        messages=[
            {
                "role": "user",
                "content": "Merhaba Elena, bugün nasılsın?",
            }
        ],
    )

    print("\nElena:")
    print(response)


if __name__ == "__main__":
    asyncio.run(main())
