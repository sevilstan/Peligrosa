"""Roleplay API provider: request shape, errors and balance watching."""

import asyncio
import logging
from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from app.core.config import settings
from app.providers.roleplay_provider import (
    LOW_BALANCE_WARN_INTERVAL_SECONDS,
    RoleplayProvider,
)
from app.telegram.bot import build_ai_provider, build_inner_provider


class FakeRaw:
    def __init__(self, text="Hello!", balance="12.50"):
        self.headers = {} if balance is None else {"X-Balance-USD": balance}
        self._text = text

    def parse(self):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._text))])


class FakeCreate:
    def __init__(self, raw=None, error=None):
        self.raw, self.error, self.calls = raw or FakeRaw(), error, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.raw


def make_client(create):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=create))
    )


def status_error(code):
    request = httpx.Request("POST", "https://api.roleplayapi.com/v1/chat/completions")
    response = httpx.Response(code, request=request, json={"error": {"type": "x"}})
    return openai.APIStatusError("secret prompt text in message", response=response, body=None)


def run(coro):
    return asyncio.run(coro)


def test_request_uses_the_model_and_puts_the_system_prompt_first():
    create = FakeCreate()
    provider = RoleplayProvider(client=make_client(create))
    reply = run(provider.generate_response("You are Amy.", [{"role": "user", "content": "hi"}]))

    assert reply == "Hello!"
    call = create.calls[0]
    assert call["model"] == "uncensored"
    assert call["messages"] == [
        {"role": "system", "content": "You are Amy."},
        {"role": "user", "content": "hi"},
    ]


def test_an_empty_reply_is_an_empty_string():
    provider = RoleplayProvider(client=make_client(FakeCreate(FakeRaw(text=None))))
    assert run(provider.generate_response("s", [])) == ""


def test_a_key_is_required_and_the_real_client_points_at_the_service(monkeypatch):
    monkeypatch.setattr(settings, "ROLEPLAY_API_KEY", "")
    with pytest.raises(RuntimeError, match="ROLEPLAY_API_KEY"):
        RoleplayProvider()

    monkeypatch.setattr(settings, "ROLEPLAY_API_KEY", "test-key-not-real")
    provider = RoleplayProvider()
    assert str(provider.client.base_url).rstrip("/") == "https://api.roleplayapi.com/v1"
    assert provider.model == settings.ROLEPLAY_MODEL


def test_out_of_credit_and_bad_key_are_logged_as_errors_without_text(caplog):
    for code, expected in ((402, "out of credit"), (401, "key was rejected")):
        provider = RoleplayProvider(client=make_client(FakeCreate(error=status_error(code))))
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            with pytest.raises(openai.APIStatusError):
                run(provider.generate_response("secret prompt text", []))
        assert expected in caplog.text
        assert "secret" not in caplog.text


def test_other_errors_pass_through_quietly(caplog):
    provider = RoleplayProvider(client=make_client(FakeCreate(error=status_error(403))))
    with caplog.at_level(logging.ERROR):
        with pytest.raises(openai.APIStatusError):
            run(provider.generate_response("s", []))
    assert caplog.text == ""


def test_the_balance_is_tracked_and_a_low_one_warns_once_per_interval(monkeypatch, caplog):
    monkeypatch.setattr(settings, "ROLEPLAY_LOW_BALANCE_USD", 3.0)
    now = [1000.0]
    create = FakeCreate(FakeRaw(balance="12.50"))
    provider = RoleplayProvider(client=make_client(create), clock=lambda: now[0])

    with caplog.at_level(logging.ERROR):
        run(provider.generate_response("s", []))
        assert provider.balance_usd == 12.5 and caplog.text == ""

        create.raw = FakeRaw(balance="2.40")
        run(provider.generate_response("s", []))
        assert "balance is low: $2.40" in caplog.text
        assert caplog.text.count("balance is low") == 1

        now[0] += 60
        run(provider.generate_response("s", []))
        assert caplog.text.count("balance is low") == 1  # not again so soon

        now[0] += LOW_BALANCE_WARN_INTERVAL_SECONDS
        run(provider.generate_response("s", []))
        assert caplog.text.count("balance is low") == 2


def test_a_missing_or_garbage_balance_header_is_ignored(caplog):
    for header in (None, "abc", "", "nan"):
        provider = RoleplayProvider(client=make_client(FakeCreate(FakeRaw(balance=header))))
        with caplog.at_level(logging.ERROR):
            assert run(provider.generate_response("s", [])) == "Hello!"
        assert provider.balance_usd is None and caplog.text == ""


def test_provider_choice_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setattr(settings, "ROLEPLAY_API_KEY", "test-key-not-real")

    monkeypatch.setattr(settings, "AI_PROVIDER", "roleplay")
    assert type(build_inner_provider()).__name__ == "RoleplayProvider"
    assert type(build_ai_provider().inner.inner).__name__ == "RoleplayProvider"

    monkeypatch.setattr(settings, "AI_PROVIDER", " Groq ")
    assert type(build_inner_provider()).__name__ == "GroqProvider"

    monkeypatch.setattr(settings, "AI_PROVIDER", "nonsense")
    with pytest.raises(RuntimeError, match="Unknown AI_PROVIDER"):
        build_inner_provider()
