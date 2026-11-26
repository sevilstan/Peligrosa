"""Make replies feel typed by a person: a few short bubbles with pauses.

The AI still answers with ONE text in ONE request. Here that text is cut at
paragraph/sentence borders into at most a few bubbles, and each later bubble
is preceded by "typing..." and a short pause that grows with its length. The
total pause is capped so nobody waits long. Short replies stay one bubble.
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_PARAGRAPH = re.compile(r"\n+")
_MIN_PIECE = 25  # shorter fragments are glued to a neighbour

# Tests replace this to avoid real waiting.
_sleep = asyncio.sleep


@dataclass(frozen=True)
class PacingConfig:
    enabled: bool = True
    max_bubbles: int = 3
    short_reply_chars: int = 120  # at or below this, never split
    chars_per_second: float = 40.0  # imagined typing speed
    min_pause: float = 0.8
    max_pause: float = 2.5
    max_total_seconds: float = 5.0  # all pauses of one reply together

    @classmethod
    def from_settings(cls, settings) -> "PacingConfig":
        return cls(
            enabled=settings.PACING_ENABLED,
            max_bubbles=max(1, settings.PACING_MAX_BUBBLES),
            max_total_seconds=max(0.0, settings.PACING_MAX_TOTAL_SECONDS),
        )


def split_bubbles(text: str, config: PacingConfig) -> list[str]:
    """Cut a reply into short bubbles without changing a single word."""
    text = text.strip()
    if not config.enabled or config.max_bubbles <= 1 or len(text) <= config.short_reply_chars:
        return [text]

    pieces = [p.strip() for p in _PARAGRAPH.split(text) if p.strip()]
    if len(pieces) == 1:
        pieces = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]

    # Tiny fragments ("Hmm.", "Ah!") read badly alone: glue them on.
    merged: list[str] = []
    for piece in pieces:
        if merged and (len(piece) < _MIN_PIECE or len(merged[-1]) < _MIN_PIECE):
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)

    # Too many bubbles: repeatedly join the two neighbours that are shortest.
    while len(merged) > config.max_bubbles:
        i = min(range(len(merged) - 1), key=lambda k: len(merged[k]) + len(merged[k + 1]))
        merged[i : i + 2] = [f"{merged[i]} {merged[i + 1]}"]

    return merged or [text]


def pause_for(text: str, config: PacingConfig) -> float:
    """How long the character "types" this bubble."""
    seconds = len(text) / config.chars_per_second
    return min(config.max_pause, max(config.min_pause, seconds))


def pauses_for(bubbles: list[str], config: PacingConfig) -> list[float]:
    """The pause BEFORE each later bubble (the first one is sent at once)."""
    pauses = [pause_for(b, config) for b in bubbles[1:]]
    total = sum(pauses)
    if total > config.max_total_seconds > 0:
        pauses = [p * config.max_total_seconds / total for p in pauses]
    elif config.max_total_seconds <= 0:
        pauses = [0.0 for _ in pauses]
    return pauses


def gap_before_reply(text: str, config: PacingConfig) -> float:
    """A short pause before another character answers in a group, so two or
    three replies do not land in the same instant."""
    if not config.enabled:
        return 0.0
    return min(1.5, max(0.8, len(text) / config.chars_per_second * 0.5))


async def play(
    bubbles: list[str],
    send: Callable[[int, str], Awaitable[None]],
    typing: Callable[[], Awaitable[None]],
    config: PacingConfig,
    lead_in: float = 0.0,
) -> None:
    """Send the bubbles one after another with typing and pauses between."""
    if lead_in > 0:
        await typing()
        await _sleep(lead_in)

    pauses = pauses_for(bubbles, config) if config.enabled else [0.0] * (len(bubbles) - 1)
    for index, bubble in enumerate(bubbles):
        if index > 0:
            if pauses[index - 1] > 0:
                await typing()
                await _sleep(pauses[index - 1])
        await send(index, bubble)
