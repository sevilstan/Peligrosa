"""A character's feelings: how it sees other characters, and its mood.

Everything is scoped by user_id AND the owning character_id: a character only
ever loads ITS OWN feelings, never another character's. Values are numbers
(for rules and updates) that are turned into behaviour hints for the prompt;
they are never shown to the user.

Writers only flush; the caller commits (like CharacterMemoryService).
Anything that comes from a model is untrusted: unknown keys are ignored,
numbers are clamped, one update can only move a value a little.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import func

from app.models.character_emotion import CharacterEmotion
from app.models.character_relationship import DIMENSIONS, CharacterRelationship

# One update may move a value at most this far: feelings change gradually.
MAX_STEP = 5

NEUTRAL = {
    "trust": 50,
    "affection": 50,
    "respect": 50,
    "jealousy": 0,
    "rivalry": 0,
    "familiarity": 0,
    "tension": 0,
}

MOODS = frozenset(
    {
        "happy",
        "content",
        "excited",
        "affectionate",
        "playful",
        "calm",
        "sad",
        "upset",
        "angry",
        "jealous",
        "anxious",
        "embarrassed",
    }
)

# A mood fades by this much per hour and is gone below the minimum.
DECAY_PER_HOUR = 10
MIN_INTENSITY = 10
_REASON_LIMIT = 200


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


class CharacterRelationshipService:
    def __init__(self, session):
        self.session = session

    async def get_for_speaker(self, user_id, character_id, other_ids) -> dict:
        """{other_character_id: CharacterRelationship}, only rows OWNED by
        character_id for this user."""
        if not other_ids:
            return {}

        rows = (
            await self.session.execute(
                select(CharacterRelationship).where(
                    CharacterRelationship.user_id == user_id,
                    CharacterRelationship.character_id == character_id,
                    CharacterRelationship.other_character_id.in_(list(other_ids)),
                )
            )
        ).scalars()
        return {row.other_character_id: row for row in rows}

    async def apply_deltas(self, user_id, character_id, other_character_id, deltas: dict):
        """Move some of the feelings of character_id about other_character_id.

        deltas: {"trust": 3, "tension": -2}. Unknown names and non-integers are
        ignored; each change is limited to +-MAX_STEP and results stay 0..100.
        """
        if character_id == other_character_id:
            raise ValueError("A character has no relationship with itself.")

        current = (
            await self.session.execute(
                select(CharacterRelationship).where(
                    CharacterRelationship.user_id == user_id,
                    CharacterRelationship.character_id == character_id,
                    CharacterRelationship.other_character_id == other_character_id,
                )
            )
        ).scalar_one_or_none()

        values = {name: getattr(current, name) if current else NEUTRAL[name] for name in DIMENSIONS}

        for name, delta in (deltas or {}).items():
            if name not in values or isinstance(delta, bool) or not isinstance(delta, int):
                continue
            values[name] = _clamp(values[name] + _clamp(delta, -MAX_STEP, MAX_STEP))

        await self.session.execute(
            pg_insert(CharacterRelationship)
            .values(
                user_id=user_id,
                character_id=character_id,
                other_character_id=other_character_id,
                **values,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "character_id", "other_character_id"],
                set_={**values, "updated_at": func.now()},
            )
        )
        return values


@dataclass(frozen=True)
class Emotion:
    mood: str
    intensity: int  # effective, after fading
    reason: str | None


class CharacterEmotionService:
    def __init__(self, session):
        self.session = session

    async def set_emotion(self, user_id, character_id, mood, intensity, reason=None):
        if mood not in MOODS:
            raise ValueError("Unknown mood.")
        if isinstance(intensity, bool) or not isinstance(intensity, int):
            raise ValueError("Intensity must be a whole number.")

        values = {
            "mood": mood,
            "intensity": _clamp(intensity),
            "reason": (reason or "").strip()[:_REASON_LIMIT] or None,
        }
        await self.session.execute(
            pg_insert(CharacterEmotion)
            .values(user_id=user_id, character_id=character_id, **values)
            .on_conflict_do_update(
                index_elements=["user_id", "character_id"],
                set_={**values, "updated_at": func.now()},
            )
        )

    async def get_emotion(self, user_id, character_id, now: datetime | None = None) -> Emotion | None:
        """The current mood after fading, or None when the character is neutral."""
        row = (
            await self.session.execute(
                select(CharacterEmotion).where(
                    CharacterEmotion.user_id == user_id,
                    CharacterEmotion.character_id == character_id,
                )
            )
        ).scalar_one_or_none()

        if row is None:
            return None

        now = now or datetime.now(timezone.utc)
        hours = max(0.0, (now - row.updated_at).total_seconds() / 3600)
        effective = int(row.intensity - DECAY_PER_HOUR * hours)

        if effective < MIN_INTENSITY:
            return None
        return Emotion(row.mood, effective, row.reason)
