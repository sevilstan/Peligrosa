import asyncio

from app.services.conversation_summarizer import ConversationSummarizer


async def main():
    summarizer = ConversationSummarizer()

    messages = [
        {
            "role": "user",
            "content": "Bugün iş yerinde patronumla tartıştım.",
        },
        {
            "role": "assistant",
            "content": "Üzüldüm. Ne yaşandı?",
        },
        {
            "role": "user",
            "content": "Raporumu beğenmedi. Yarın onunla tekrar konuşacağım.",
        },
    ]

    print("\n--- İLK ÖZET ---")

    summary = await summarizer.summarize(messages)

    print(summary)

    new_messages = [
        {
            "role": "user",
            "content": "Bugün patronumla konuştum. Özür diledi ve sorun çözüldü.",
        },
        {
            "role": "assistant",
            "content": "Buna sevindim! İçinin rahatlamasına sevindim.",
        },
    ]

    print("\n--- GÜNCELLENMİŞ ÖZET ---")

    updated_summary = await summarizer.summarize(
        messages=new_messages,
        existing_summary=summary,
    )

    print(updated_summary)    
    
    # ÜÇÜNCÜ AŞAMA: Yeni bir gelişme
    third_messages = [
        {
            "role": "user",
            "content": "Bu arada patronumla yeni bir proje üzerinde çalışmaya başladık."
        },
        {
            "role": "assistant",
            "content": "Bu harika! Umarım birlikte güzel işler çıkarırsınız."
        },
    ]

    updated_summary = await summarizer.summarize(
        messages=third_messages,
        existing_summary=updated_summary,
    )

    print("\n--- ÜÇÜNCÜ ÖZET ---")
    print(updated_summary)



if __name__ == "__main__":
    asyncio.run(main())
