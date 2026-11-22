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
