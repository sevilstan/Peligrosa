import asyncio

import pytest

from app.providers.base import AIProvider
from app.providers.rate_limited_provider import RateLimitedProvider, RateLimitTimeout


class Inner(AIProvider):
    model = "m1"

    def __init__(self, delay=0.0):
        self.calls = []
        self.delay = delay
        self.running = 0
        self.max_running = 0

    async def generate_response(self, system_prompt, messages):
        self.calls.append(system_prompt)
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            await asyncio.sleep(self.delay)
            if system_prompt == "boom":
                raise RuntimeError("provider down")
            return f"re:{system_prompt}"
        finally:
            self.running -= 1


class FakeTime:
    """A clock that only moves when somebody sleeps."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(round(seconds, 3))
        self.now += seconds
        await asyncio.sleep(0)


def limited(inner, per_minute=2, concurrent=4, max_wait=30, fake=None):
    fake = fake or FakeTime()
    return RateLimitedProvider(inner, per_minute, concurrent, max_wait, clock=fake.clock, sleep=fake.sleep), fake


def test_calls_under_the_limit_do_not_wait():
    async def scenario():
        provider, fake = limited(Inner(), per_minute=3)
        assert [await provider.generate_response(str(i), []) for i in range(3)] == ["re:0", "re:1", "re:2"]
        assert fake.sleeps == []

    asyncio.run(scenario())


def test_extra_calls_wait_until_the_window_reopens():
    async def scenario():
        provider, fake = limited(Inner(), per_minute=2)
        await provider.generate_response("a", [])
        fake.now += 10
        await provider.generate_response("b", [])
        await provider.generate_response("c", [])  # must wait for "a" to leave the window
        assert fake.sleeps == [50.0]

        fake.now += 100  # everything has expired
        fake.sleeps.clear()
        await provider.generate_response("d", [])
        assert fake.sleeps == []

    asyncio.run(scenario())


def test_waiting_requests_start_in_arrival_order():
    async def scenario():
        inner = Inner()
        provider, _ = limited(inner, per_minute=1, concurrent=4)
        results = await asyncio.gather(*(provider.generate_response(str(i), []) for i in range(5)))
        assert results == [f"re:{i}" for i in range(5)]
        assert inner.calls == ["0", "1", "2", "3", "4"]

    asyncio.run(scenario())


def test_a_request_that_waits_too_long_is_dropped_without_calling_the_provider():
    async def scenario():
        inner = Inner()
        provider = RateLimitedProvider(inner, 1, 4, 0.05)  # real clock and sleep
        await provider.generate_response("first", [])
        with pytest.raises(RateLimitTimeout):
            await provider.generate_response("second", [])  # would wait ~60s
        assert inner.calls == ["first"]

    asyncio.run(scenario())


def test_dropped_requests_do_not_block_the_ones_behind_them_forever():
    async def scenario():
        inner = Inner()
        provider = RateLimitedProvider(inner, 1, 4, 0.05)
        await provider.generate_response("first", [])
        results = await asyncio.gather(
            provider.generate_response("x", []), provider.generate_response("y", []), return_exceptions=True
        )
        assert all(isinstance(r, RateLimitTimeout) for r in results)

    asyncio.run(scenario())


def test_concurrency_is_capped():
    async def scenario():
        inner = Inner(delay=0.02)
        provider, _ = limited(inner, per_minute=100, concurrent=2)
        await asyncio.gather(*(provider.generate_response(str(i), []) for i in range(8)))
        assert inner.max_running == 2

    asyncio.run(scenario())


def test_provider_errors_pass_through_and_free_the_concurrency_slot():
    async def scenario():
        inner = Inner()
        provider, _ = limited(inner, per_minute=100, concurrent=1)
        with pytest.raises(RuntimeError, match="provider down"):
            await provider.generate_response("boom", [])
        assert await provider.generate_response("ok", []) == "re:ok"

    asyncio.run(scenario())


def test_model_is_passed_through_and_limits_are_validated():
    assert limited(Inner())[0].model == "m1"
    for args in ((0, 1, 1), (1, 0, 1), (1, 1, 0)):
        with pytest.raises(ValueError):
            RateLimitedProvider(Inner(), *args)


def test_the_bot_uses_the_limiter_with_the_configured_numbers(monkeypatch):
    from app.core.config import settings
    from app.telegram.bot import build_ai_provider

    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setattr(settings, "AI_MAX_REQUESTS_PER_MINUTE", 7)
    monkeypatch.setattr(settings, "AI_MAX_QUEUE_WAIT_SECONDS", 12.0)

    from app.providers.usage_tracking_provider import UsageTrackingProvider

    tracked = build_ai_provider()
    assert isinstance(tracked, UsageTrackingProvider)
    provider = tracked.inner
    assert isinstance(provider, RateLimitedProvider)
    assert provider.max_per_minute == 7 and provider.max_wait == 12.0
    assert provider.model == settings.GROQ_MODEL
