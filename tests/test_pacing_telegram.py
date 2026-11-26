"""Pacing in the real chat flow: bubbles, headers, pauses, the off switch."""

from app.core.config import settings
from app.telegram import pacing
from tests.telegram_harness import Harness, add_characters, callback_update, message_update
from tests.test_conversation_engine import ScriptedProvider
from tests.test_group_messaging import TRIO, DirectorProvider
from tests.test_pacing import LONG, norm

PEOPLE = [("Amy", "amy", 0, True)]


def bubbles_after(bot, start):
    return bot.session.named("SendMessage")[start:]


def test_a_long_reply_arrives_as_bubbles_and_only_the_first_has_the_name(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path, ScriptedProvider(chat_reply=LONG))
        await bot.send(callback_update("open:amy"))
        before = len(bot.session.named("SendMessage"))

        await bot.send(message_update("hi"))

        sent = bubbles_after(bot, before)
        assert len(sent) >= 2
        assert sent[0]["text"].startswith("<b>Amy:</b> ") and sent[0]["parse_mode"] == "HTML"
        assert all("<b>Amy:</b>" not in m["text"] for m in sent[1:])
        body = [sent[0]["text"].removeprefix("<b>Amy:</b> ")] + [m["text"] for m in sent[1:]]
        assert norm(body) == norm([LONG])
        assert bot.session.named("SendChatAction")  # "typing..." between bubbles

    run_db(scenario)


def test_the_off_switch_sends_one_message_at_once(run_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PACING_ENABLED", False)

    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path, ScriptedProvider(chat_reply=LONG))
        await bot.send(callback_update("open:amy"))
        before = len(bot.session.named("SendMessage"))

        await bot.send(message_update("hi"))

        assert len(bubbles_after(bot, before)) == 1

    run_db(scenario)


def test_a_second_speaker_in_a_group_waits_but_the_first_does_not(run_db, tmp_path, monkeypatch):
    sleeps = []

    async def scenario(maker):
        await add_characters(maker, TRIO)
        provider = DirectorProvider(chat_reply="hi there")
        bot = Harness(maker, tmp_path, provider)
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))

        async def record(seconds):
            # How many messages were already out when this pause began.
            sleeps.append((seconds, len(bot.session.named("SendMessage"))))

        monkeypatch.setattr(pacing, "_sleep", record)
        before = len(bot.session.named("SendMessage"))
        await bot.send(message_update("hello you two"))

        assert sleeps, "the second speaker should have waited"
        assert sleeps[0][1] > before  # the first speaker was sent without any pause
        assert all(0.8 <= s <= 1.5 for s, _ in sleeps)

    run_db(scenario)
