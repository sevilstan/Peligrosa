import asyncio

from app.services.conversation_summarizer import ConversationSummarizer


class CapturingProvider:
    def __init__(self, reply="  Kullanıcı yalnız hissediyor.  "):
        self.reply = reply
        self.system_prompt = ""
        self.user_message = ""

    async def generate_response(self, system_prompt, messages):
        self.system_prompt = system_prompt
        self.user_message = messages[0]["content"]
        return self.reply


def summarize(provider, messages=None, existing_summary=None):
    summarizer = ConversationSummarizer(ai_provider=provider)
    return asyncio.run(
        summarizer.summarize(
            messages=messages
            or [
                {"role": "user", "content": "sadece yalnızım"},
                {"role": "assistant", "content": "I'm sorry, but I can't help with that."},
            ],
            existing_summary=existing_summary,
        )
    )


def test_summary_is_returned_stripped():
    assert summarize(CapturingProvider()) == "Kullanıcı yalnız hissediyor."


def test_summary_language_follows_the_user_not_the_instructions():
    provider = CapturingProvider()

    summarize(provider)

    # Stated in the system prompt...
    assert "language the USER writes in" in provider.system_prompt
    # ...and repeated right after the data, where models obey it best.
    assert provider.user_message.rstrip().endswith(
        "in the same language as the USER lines above."
    )


def test_summary_must_be_plain_text():
    provider = CapturingProvider()

    summarize(provider)

    assert "no markdown" in provider.system_prompt
    assert "plain text" in provider.user_message


def test_assistant_refusals_are_not_recorded():
    provider = CapturingProvider()

    summarize(provider)

    assert "refusals, apologies and statements about" in provider.system_prompt


def test_existing_summary_and_messages_are_passed_through():
    provider = CapturingProvider()

    summarize(provider, existing_summary="Eski özet.")

    assert "EXISTING CONVERSATION SUMMARY:\nEski özet." in provider.user_message
    assert "USER: sadece yalnızım" in provider.user_message
    assert "ASSISTANT: I'm sorry" in provider.user_message
