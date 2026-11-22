import pytest

from app.core.config import settings
from app.providers.groq_provider import GroqProvider
from app.providers.openai_provider import OpenAIProvider


def test_groq_provider_without_api_key_fails_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")

    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not set"):
        GroqProvider()


def test_openai_provider_without_api_key_fails_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        OpenAIProvider()


@pytest.mark.parametrize(
    "provider_class, key_name",
    [(GroqProvider, "GROQ_API_KEY"), (OpenAIProvider, "OPENAI_API_KEY")],
)
def test_providers_apply_configured_timeout_and_retries(
    monkeypatch, provider_class, key_name
):
    monkeypatch.setattr(settings, key_name, "test-key-not-real")
    monkeypatch.setattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 12.5)
    monkeypatch.setattr(settings, "AI_MAX_RETRIES", 1)

    provider = provider_class()

    assert provider.client.timeout == 12.5
    assert provider.client.max_retries == 1


def test_error_for_missing_key_never_contains_a_key_value(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")

    with pytest.raises(RuntimeError) as error:
        GroqProvider()

    assert "gsk_" not in str(error.value)


def _reply_stub(captured, result):
    async def create(**kwargs):
        captured.update(kwargs)
        return result

    return create


def test_groq_provider_uses_explicit_model_then_falls_back_to_settings(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setattr(settings, "GROQ_MODEL", "env-model")
    answer = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))]
    )

    for explicit, expected in [("override-model", "override-model"), (None, "env-model")]:
        captured = {}
        provider = GroqProvider(model=explicit)
        provider.client.chat.completions.create = _reply_stub(captured, answer)

        reply = asyncio.run(provider.generate_response("system", [{"role": "user", "content": "x"}]))

        assert reply == "hi"
        assert captured["model"] == expected


def test_openai_provider_uses_explicit_model_then_falls_back_to_settings(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(settings, "OPENAI_MODEL", "env-model")
    answer = SimpleNamespace(output_text="hi")

    for explicit, expected in [("override-model", "override-model"), (None, "env-model")]:
        captured = {}
        provider = OpenAIProvider(model=explicit)
        provider.client.responses.create = _reply_stub(captured, answer)

        reply = asyncio.run(provider.generate_response("system", [{"role": "user", "content": "x"}]))

        assert reply == "hi"
        assert captured["model"] == expected


def test_groq_provider_turns_a_missing_reply_into_an_empty_string(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key-not-real")
    answer = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
    )
    provider = GroqProvider()
    provider.client.chat.completions.create = _reply_stub({}, answer)

    assert asyncio.run(provider.generate_response("system", [])) == ""
