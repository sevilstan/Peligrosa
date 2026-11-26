"""The Xavira provider against a fake network."""

import asyncio
import logging

import pytest

from app.providers import xavira_provider
from app.providers.image_base import ImageGenerationError, ImageGenerationRefused
from app.providers.xavira_provider import HttpResponse, XaviraImageProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
HOST = "https://pub-abc123.r2.dev/x/gen.png"
KEY = "xav_live_SECRETKEY"


class FakeTransport:
    """Answers from a script: a list of (status, json) or raw bytes responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, url, *, headers=None, json=None, max_bytes=1_000_000):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "json": json})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, bytes):
            return HttpResponse(200, {}, item)
        status, body = item
        return HttpResponse(status, {}, b"", body)


@pytest.fixture(autouse=True)
def no_polling_wait(monkeypatch):
    async def instant(seconds):
        return None

    monkeypatch.setattr(xavira_provider, "_sleep", instant)


def provider(transport, **kw):
    return XaviraImageProvider(api_key=KEY, transport=transport, **kw)


def run(coro):
    return asyncio.run(coro)


def done(**extra):
    return {"generation_id": "g1", "status": "completed", "output_url": HOST, "credits_remaining": 20, **extra}


def test_an_inline_result_is_downloaded_with_the_right_request():
    transport = FakeTransport((201, done()), PNG)
    data = run(provider(transport).generate_image("sitting, in a cafe", character_ref="chr-1234abcd"))

    assert data == PNG
    call = transport.calls[0]
    assert call["url"] == "https://api.xavira.ai/v1/images:generate"
    assert call["json"] == {"character_id": "chr-1234abcd", "prompt": "sitting, in a cafe", "resolution": "hd_portrait"}
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert call["headers"]["Idempotency-Key"]


def test_a_slow_picture_is_polled_until_it_is_ready():
    pending = {"generation_id": "g1", "status": "pending"}
    transport = FakeTransport((202, pending), (200, {"status": "pending"}), (200, done()), PNG)

    assert run(provider(transport).generate_image("p", character_ref="chr-1234abcd")) == PNG
    assert [c["method"] for c in transport.calls] == ["POST", "GET", "GET", "GET"]
    assert transport.calls[1]["url"].endswith("/v1/generations/g1")


@pytest.mark.parametrize("state", ["failed", "cancelled", "timed_out"])
def test_a_failed_generation_is_an_error(state):
    transport = FakeTransport((202, {"generation_id": "g1", "status": "pending"}), (200, {"status": state}))
    with pytest.raises(ImageGenerationError):
        run(provider(transport).generate_image("p", character_ref="chr-1234abcd"))


def test_waiting_too_long_gives_up():
    now = [0.0]

    def clock():
        now[0] += 30
        return now[0]

    transport = FakeTransport(
        (202, {"generation_id": "g1", "status": "pending"}), *[(200, {"status": "pending"})] * 5
    )
    with pytest.raises(ImageGenerationError, match="too long"):
        run(provider(transport, max_wait=60, clock=clock).generate_image("p", character_ref="chr-1234abcd"))


def test_moderation_is_a_refusal_without_an_alert(caplog):
    transport = FakeTransport((422, {"error": {"code": "moderation_blocked", "message": "x"}}))
    with caplog.at_level(logging.WARNING), pytest.raises(ImageGenerationRefused):
        run(provider(transport).generate_image("p", character_ref="chr-1234abcd"))
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize(
    "status,code,words",
    [
        (402, "insufficient_credits", "out of credit"),
        (401, "unauthorized", "key was rejected"),
        (404, "character_not_found", "image_character_id"),
    ],
)
def test_problems_only_the_operator_can_fix_raise_an_alert(caplog, status, code, words):
    transport = FakeTransport((status, {"error": {"code": code}}))
    with caplog.at_level(logging.ERROR), pytest.raises(ImageGenerationError):
        run(provider(transport).generate_image("SECRET PROMPT", character_ref="chr-1234abcd"))

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(words in m for m in errors)
    assert all("SECRET PROMPT" not in m and KEY not in m for m in errors)


@pytest.mark.parametrize("status", [429, 500, 502])
def test_temporary_trouble_is_a_quiet_error(caplog, status):
    transport = FakeTransport((status, {"error": {"code": "rate_limited"}}))
    with caplog.at_level(logging.WARNING), pytest.raises(ImageGenerationError):
        run(provider(transport).generate_image("p", character_ref="chr-1234abcd"))
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_network_trouble_is_an_error():
    import aiohttp

    transport = FakeTransport(aiohttp.ClientError("boom"))
    with pytest.raises(ImageGenerationError):
        run(provider(transport).generate_image("p", character_ref="chr-1234abcd"))


@pytest.mark.parametrize(
    "url",
    ["http://pub-abc.r2.dev/a.png", "https://evil.example.com/a.png", "https://r2.dev.evil.com/a.png", "file:///etc/passwd"],
)
def test_pictures_are_only_fetched_from_xaviras_storage(url):
    transport = FakeTransport((201, done(output_url=url)))
    with pytest.raises(ImageGenerationError):
        run(provider(transport).generate_image("p", character_ref="chr-1234abcd"))
    assert len(transport.calls) == 1  # nothing was downloaded


@pytest.mark.parametrize("payload", [b"<html>nope</html>", b"", b"x" * 20])
def test_a_download_that_is_not_a_picture_is_refused(payload):
    transport = FakeTransport((201, done()), payload)
    with pytest.raises(ImageGenerationError):
        run(provider(transport).generate_image("p", character_ref="chr-1234abcd"))


def test_a_character_id_is_required_and_so_is_a_key():
    with pytest.raises(ImageGenerationError):
        run(provider(FakeTransport()).generate_image("p"))
    with pytest.raises(ValueError):
        XaviraImageProvider(api_key="")


def test_low_balance_alerts_once_per_interval(caplog):
    now = [1000.0]
    transport = FakeTransport(*[(201, done(credits_remaining=3)), PNG] * 3)
    p = provider(transport, clock=lambda: now[0], low_balance=5)

    with caplog.at_level(logging.ERROR):
        run(p.generate_image("p", character_ref="chr-1234abcd"))
        run(p.generate_image("p", character_ref="chr-1234abcd"))
        assert len([r for r in caplog.records if "balance is low" in r.getMessage()]) == 1
        now[0] += xavira_provider.LOW_BALANCE_WARN_INTERVAL_SECONDS + 1
        run(p.generate_image("p", character_ref="chr-1234abcd"))
    assert len([r for r in caplog.records if "balance is low" in r.getMessage()]) == 2
    assert p.credits_remaining == 3


def test_a_healthy_balance_is_quiet(caplog):
    transport = FakeTransport((201, done(credits_remaining=500)), PNG)
    with caplog.at_level(logging.ERROR):
        run(provider(transport).generate_image("p", character_ref="chr-1234abcd"))
    assert not caplog.records
