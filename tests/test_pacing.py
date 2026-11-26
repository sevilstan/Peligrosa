"""Replies come as a few short bubbles with typing pauses."""

import pytest

from app.telegram import pacing
from app.telegram.pacing import PacingConfig, pause_for, pauses_for, play, split_bubbles

CFG = PacingConfig()
LONG = (
    "Aaa hoş geldin, seni görmek çok güzel! Bugün nasıl geçti, anlat bakalım. "
    "Ben de tam seni düşünüyordum, yazacaktım. Akşam için bir planın var mı yoksa evde mi kalıyorsun?"
)


def norm(parts):
    return " ".join(" ".join(parts).split())


def test_short_replies_stay_one_bubble():
    assert split_bubbles("Haha evet 😄", CFG) == ["Haha evet 😄"]
    assert split_bubbles("x" * CFG.short_reply_chars, CFG) == ["x" * CFG.short_reply_chars]
    # Short but several sentences: still one bubble.
    two = "Hello there my friend, welcome. How was your day today, tell me more."
    assert len(two) <= CFG.short_reply_chars and split_bubbles(two, CFG) == [two]


def test_a_long_reply_becomes_a_few_bubbles_without_losing_a_word():
    bubbles = split_bubbles(LONG, CFG)
    assert 2 <= len(bubbles) <= CFG.max_bubbles
    assert norm(bubbles) == norm([LONG])


def test_paragraphs_are_respected_and_capped():
    text = "\n\n".join(f"Paragraph number {i} has a fair amount of words in it." for i in range(6))
    bubbles = split_bubbles(text, CFG)
    assert len(bubbles) == CFG.max_bubbles
    assert norm(bubbles) == norm([text])


def test_tiny_fragments_are_not_sent_alone():
    text = "Hmm. Ah! " + "This is the real sentence with enough words to count as one. " * 3
    assert all(len(b) >= 25 for b in split_bubbles(text, CFG))


def test_disabled_or_single_bubble_config_never_splits():
    assert split_bubbles(LONG, PacingConfig(enabled=False)) == [LONG]
    assert split_bubbles(LONG, PacingConfig(max_bubbles=1)) == [LONG]


def test_pauses_grow_with_length_and_the_total_is_capped():
    assert pause_for("hi", CFG) == CFG.min_pause
    assert pause_for("x" * 1000, CFG) == CFG.max_pause
    pauses = pauses_for(["a" * 200] * 5, CFG)
    assert len(pauses) == 4 and sum(pauses) == pytest.approx(CFG.max_total_seconds)
    assert pauses_for(["a", "b"], PacingConfig(max_total_seconds=0)) == [0.0]


def test_play_sends_in_order_with_typing_and_a_pause_before_each_later_bubble(monkeypatch):
    log = []

    async def fake_sleep(seconds):
        log.append(("sleep", round(seconds, 2)))

    monkeypatch.setattr(pacing, "_sleep", fake_sleep)

    async def send(i, text):
        log.append(("send", i))

    async def typing():
        log.append(("typing",))

    import asyncio

    asyncio.run(play(["one " * 10, "two " * 10, "three " * 10], send, typing, CFG))

    kinds = [e[0] for e in log]
    assert kinds == ["send", "typing", "sleep", "send", "typing", "sleep", "send"]
    assert [e[1] for e in log if e[0] == "send"] == [0, 1, 2]


def test_lead_in_waits_before_the_first_bubble(monkeypatch):
    log = []

    async def fake_sleep(seconds):
        log.append("sleep")

    monkeypatch.setattr(pacing, "_sleep", fake_sleep)

    async def send(i, text):
        log.append("send")

    async def typing():
        log.append("typing")

    import asyncio

    asyncio.run(play(["hi"], send, typing, CFG, lead_in=1.0))
    assert log == ["typing", "sleep", "send"]
