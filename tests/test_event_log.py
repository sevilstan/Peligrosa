"""The activity log: command and button names only, never what users typed."""

import json
from datetime import datetime, timezone

from aiogram.types import Update
from sqlalchemy import select

from app.models import User, UserEvent
from app.services.event_log import event_name
from app.services.stats_service import StatsService
from app.services.user_data_service import UserDataService
from app.services.user_export_service import UserExportService
from app.telegram import middlewares
from tests.telegram_harness import Harness, add_characters, callback_update, message_update

KNOWN = {"photo", "start", "art"}


def build(update) -> Update:
    return update if isinstance(update, Update) else Update.model_validate(update)


def test_commands_are_named_only_when_they_are_ours():
    assert event_name(build(message_update("/photo")), KNOWN) == "cmd_photo"
    assert event_name(build(message_update("/Photo@MyBot now please")), KNOWN) == "cmd_photo"
    assert event_name(build(message_update("/hack my secret password")), KNOWN) == "cmd_unknown"
    assert event_name(build(message_update("/")), KNOWN) == "cmd_unknown"


def test_plain_text_is_never_logged():
    assert event_name(build(message_update("hello there, my secret")), KNOWN) is None
    assert event_name(build(message_update("photo")), KNOWN) is None


def test_buttons_are_named_by_their_first_word_only():
    assert event_name(build(callback_update("open:amy")), KNOWN) == "btn_open"
    assert event_name(build(callback_update("imgy")), KNOWN) == "btn_imgy"
    assert event_name(build(callback_update("pic:3")), KNOWN) == "btn_pic"
    assert event_name(build(callback_update("noop")), KNOWN) is None
    assert event_name(build(callback_update("Weird DATA with spaces")), KNOWN) == "btn_other"


async def names(maker):
    async with maker() as s:
        return [e for e in (await s.execute(select(UserEvent.name).order_by(UserEvent.created_at))).scalars()]


def test_the_bot_records_commands_and_buttons(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/start"))
        await bot.send(callback_update("open:amy"))
        await bot.send(message_update("a private sentence"))
        await bot.send(message_update("/nonsense"))
        assert await names(maker) == ["cmd_start", "btn_open", "cmd_unknown"]

    run_db(scenario)


def test_plain_chat_text_causes_no_logging_work(run_db, tmp_path, caplog):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        bot = Harness(maker, tmp_path)
        await bot.send(callback_update("open:amy"))
        caplog.clear()
        await bot.send(message_update("just chatting"))
        assert "Could not record an event" not in caplog.text

    run_db(scenario)


def test_a_logging_failure_never_breaks_the_bot(run_db, tmp_path, monkeypatch):
    async def scenario(maker):
        monkeypatch.setattr(middlewares, "event_name", lambda *_: "x" * 80)  # too long for the column
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/start"))
        assert any("18+" in text for text in bot.texts())  # the user still got the welcome
        assert await names(maker) == []

    run_db(scenario)


async def user_of(maker, telegram_id):
    async with maker() as s:
        return (await s.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()


def test_deleting_data_removes_only_that_users_events(run_db, tmp_path):
    async def scenario(maker):
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/start", user_id=1001))
        await bot.send(message_update("/start", user_id=2002, first="Bo"))
        mine = await user_of(maker, 1001)
        async with maker() as s:
            await UserDataService(s).delete_all(mine.id)
            rows = (await s.execute(select(UserEvent.user_id))).scalars().all()
        assert len(rows) == 1 and rows[0] != mine.id

    run_db(scenario)


def test_export_lists_only_the_users_own_actions(run_db, tmp_path):
    async def scenario(maker):
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/start", user_id=1001))
        await bot.send(message_update("/terms", user_id=2002, first="Bo"))
        mine = await user_of(maker, 1001)
        async with maker() as s:
            data = json.loads(await UserExportService(s).build(mine))
        assert [e["action"] for e in data["activity_log"]] == ["cmd_start"]

    run_db(scenario)


def test_stats_show_the_most_used_actions_of_the_last_day(run_db, tmp_path):
    async def scenario(maker):
        bot = Harness(maker, tmp_path)
        for _ in range(3):
            await bot.send(message_update("/terms"))
        await bot.send(message_update("/start"))
        mine = await user_of(maker, 1001)
        async with maker() as s:
            for _ in range(5):  # old activity must not count for the last 24 hours
                s.add(UserEvent(user_id=mine.id, name="cmd_old", created_at=datetime(2020, 1, 1, tzinfo=timezone.utc)))
            await s.commit()
        async with maker() as s:
            stats = await StatsService(s, clock=lambda: datetime.now(timezone.utc)).collect()
        assert stats.top_actions_24h[0] == ("cmd_terms", 3)
        from app.services.stats_service import format_stats

        assert "Most used: cmd_terms 3, cmd_start 1" in format_stats(stats)

    run_db(scenario)
