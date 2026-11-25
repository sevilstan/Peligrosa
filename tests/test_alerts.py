"""Operator alerts for ERROR logs."""

import asyncio
import logging

import pytest

from app.core.alerts import (
    MAX_TEXT,
    AlertHandler,
    AlertThrottle,
    build_sender,
    install_alerts,
    parse_admin_ids,
    remove_alerts,
)
from app.providers.base import AIProvider
from app.providers.usage_tracking_provider import UsageTrackingProvider
from tests.telegram_harness import FakeSession
from aiogram import Bot


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_handler(max_per_hour=20, dedup=600):
    clock = Clock()
    sent = []
    handler = AlertHandler(sent.append, AlertThrottle(dedup, max_per_hour, clock))
    return handler, sent, clock


def record(msg="Something broke: %s", args=("ValueError",), name="app.services.x", level=logging.ERROR, exc_info=None):
    return logging.LogRecord(name, level, "f.py", 1, msg, args, exc_info)


def test_parse_admin_ids_ignores_junk_and_duplicates():
    assert parse_admin_ids("9001, junk, 9001, -5, ,12") == [9001, -5, 12]
    assert parse_admin_ids("") == []


def test_an_error_becomes_one_short_message():
    handler, sent, _ = make_handler()
    handler.emit(record())
    assert sent == ["🚨 app.services.x\nSomething broke: ValueError"]


def test_no_traceback_and_long_or_odd_text_is_trimmed():
    handler, sent, _ = make_handler()
    try:
        raise RuntimeError("secret user text")
    except RuntimeError:
        import sys
        handler.emit(record(exc_info=sys.exc_info()))
    assert "secret user text" not in sent[0] and "Traceback" not in sent[0]

    handler.emit(record(msg="x" * 5000 + "\x00\x07", args=(), name="app.other"))
    assert len(sent[1].split("\n", 1)[1]) <= MAX_TEXT
    assert "\x00" not in sent[1]


def test_the_same_problem_is_sent_once_then_counted():
    handler, sent, clock = make_handler(dedup=600)
    handler.emit(record())
    for _ in range(5):
        clock.now += 10
        handler.emit(record())
    assert len(sent) == 1

    clock.now += 600
    handler.emit(record())
    assert len(sent) == 2 and sent[1].endswith("(+5 similar held back)")

    clock.now += 600
    handler.emit(record())
    assert "similar" not in sent[2]


def test_different_problems_are_not_merged():
    handler, sent, _ = make_handler()
    handler.emit(record(msg="Problem A", args=()))
    handler.emit(record(msg="Problem B", args=()))
    handler.emit(record(msg="Problem A", args=(), name="app.elsewhere"))
    assert len(sent) == 3


def test_there_is_an_hourly_cap_that_recovers():
    handler, sent, clock = make_handler(max_per_hour=3, dedup=0)
    for i in range(10):
        handler.emit(record(msg=f"Problem {i}", args=()))
    assert len(sent) == 3

    clock.now += 3600
    handler.emit(record(msg="Problem later", args=()))
    assert len(sent) == 4


def test_warnings_are_not_alerts_through_the_real_logger():
    handler, sent, _ = make_handler()
    log = logging.getLogger("app.test_alerts_case")
    log.addHandler(handler)
    try:
        log.warning("just a warning")
        log.info("just info")
        log.error("a real error: %s", "KeyError")
    finally:
        log.removeHandler(handler)
    assert sent == ["🚨 app.test_alerts_case\na real error: KeyError"]


def test_the_alert_system_never_alerts_about_itself():
    handler, sent, _ = make_handler()
    handler.emit(record(name="app.core.alerts"))
    assert sent == []


def test_a_broken_notifier_cannot_break_the_caller():
    def boom(_text):
        raise RuntimeError("telegram down")

    handler = AlertHandler(boom, AlertThrottle(600, 20))
    handler.emit(record())  # must not raise


# ------------------------------------------------------------------ sending


def make_bot():
    session = FakeSession()
    return Bot(token="123456:TEST", session=session), session


def test_sender_reaches_every_operator_and_survives_failures():
    async def scenario():
        bot, session = make_bot()
        await build_sender(bot, [9001, 9002])("hello")
        sends = session.named("SendMessage")
        assert [s["chat_id"] for s in sends] == [9001, 9002]
        assert all(s["text"] == "hello" for s in sends)

        class Failing(FakeSession):
            async def make_request(self, bot, method, timeout=None):
                raise RuntimeError("Forbidden: bot can't initiate conversation")

        failing = Bot(token="123456:TEST", session=Failing())
        await build_sender(failing, [1, 2])("x")  # must not raise

    asyncio.run(scenario())


def test_installed_alerts_deliver_real_errors_and_can_be_removed():
    async def scenario():
        bot, session = make_bot()
        handler, _send = install_alerts(bot, [9001], dedup_seconds=600, max_per_hour=20)
        try:
            logging.getLogger("app.telegram.bot").error("Unhandled error while processing an update: %s", "KeyError")
            await asyncio.sleep(0.05)
            texts = [s["text"] for s in session.named("SendMessage")]
            assert texts == ["🚨 app.telegram.bot\nUnhandled error while processing an update: KeyError"]
        finally:
            remove_alerts(handler)

        logging.getLogger("app.telegram.bot").error("after removal")
        await asyncio.sleep(0.05)
        assert len(session.named("SendMessage")) == 1

    asyncio.run(scenario())


# --------------------------------------------------------------- AI failures


class Failing(AIProvider):
    async def generate_response(self, system_prompt, messages):
        raise TimeoutError("secret prompt text")


def test_an_ai_failure_is_logged_as_an_error_without_text(caplog):
    tracker = UsageTrackingProvider(Failing())
    with caplog.at_level(logging.ERROR):
        with pytest.raises(TimeoutError):
            asyncio.run(tracker.generate_response("secret prompt text", []))
    assert "AI provider call failed: TimeoutError" in caplog.text
    assert "secret" not in caplog.text
