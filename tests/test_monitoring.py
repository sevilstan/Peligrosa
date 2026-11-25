"""AI usage counters and the health endpoint."""

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.providers.base import AIProvider
from app.providers.usage_tracking_provider import KEEP_DAYS, UsageTrackingProvider
from app.telegram.health import build_health_app


class Inner(AIProvider):
    model = "m1"

    def __init__(self, answer="hello", fail=False):
        self.answer, self.fail = answer, fail

    async def generate_response(self, system_prompt, messages):
        if self.fail:
            raise RuntimeError("boom with secret user text")
        return self.answer


def run(coro):
    return asyncio.run(coro)


def test_calls_failures_and_sizes_are_counted_per_day():
    day = ["2026-11-25"]
    ticks = iter([0.0, 2.0, 10.0, 11.0, 20.0, 20.0])
    tracker = UsageTrackingProvider(Inner("abcde"), clock=lambda: next(ticks), today=lambda: day[0])

    assert run(tracker.generate_response("sys", [{"role": "user", "content": "hey"}])) == "abcde"
    tracker.inner.fail = True
    with pytest.raises(RuntimeError):
        run(tracker.generate_response("sys", []))

    today = tracker.snapshot()["2026-11-25"]
    assert today["calls"] == 2 and today["failures"] == 1
    assert today["prompt_chars"] == len("sys") + len("hey") + len("sys")
    assert today["answer_chars"] == 5
    assert today["avg_seconds"] == 1.5  # (2.0 + 1.0) / 2

    day[0] = "2026-11-26"
    tracker.inner.fail = False
    run(tracker.generate_response("s", []))
    assert tracker.snapshot()["2026-11-26"]["calls"] == 1
    assert tracker.snapshot()["2026-11-25"]["calls"] == 2


def test_only_recent_days_are_kept_and_model_is_passed_through():
    day = [0]
    tracker = UsageTrackingProvider(Inner(), today=lambda: f"d{day[0]:03d}")
    for i in range(KEEP_DAYS + 3):
        day[0] = i
        run(tracker.generate_response("s", []))
    assert len(tracker.snapshot()) == KEEP_DAYS
    assert tracker.model == "m1"


def test_snapshot_holds_no_text():
    tracker = UsageTrackingProvider(Inner("private answer"))
    run(tracker.generate_response("private prompt", [{"role": "user", "content": "private msg"}]))
    assert "private" not in str(tracker.snapshot())


class FakeSession:
    def __init__(self, ok):
        self.ok = ok

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _statement):
        if not self.ok:
            raise ConnectionError("db password in message")


async def _get(path, ok=True, usage=None):
    app = build_health_app(lambda: FakeSession(ok), usage)
    async with TestClient(TestServer(app)) as client:
        response = await client.get(path)
        return response.status, await response.json()


def test_health_is_ok_when_the_database_answers():
    assert run(_get("/health")) == (200, {"status": "ok"})


def test_health_is_503_when_the_database_is_down_and_leaks_nothing():
    status, body = run(_get("/health", ok=False))
    assert status == 503 and body == {"status": "database_down"}


def test_stats_show_usage():
    tracker = UsageTrackingProvider(Inner(), today=lambda: "2026-11-25")
    run(tracker.generate_response("s", []))
    status, body = run(_get("/stats", usage=tracker))
    assert status == 200 and body["ai_usage"]["2026-11-25"]["calls"] == 1

    assert run(_get("/stats")) == (200, {"ai_usage": {}})
