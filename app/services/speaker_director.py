"""Who answers when nobody was addressed by name? One small AI call.

The rules in speaker_selection settle the clear cases (addressed by name) for
free. For the rest the director reads the last few messages and picks the
character who would naturally answer, or nobody (silence is a valid result).

Model output is untrusted: only a slug of a real member, or null, is accepted.
Any failure (provider error, invalid JSON, unknown slug) returns UNDECIDED and
the caller falls back to the rule-based choice, so a reply is never lost.
"""

import json
import logging
import re

from app.services.speaker_selection import GroupMember

logger = logging.getLogger(__name__)

DIRECTOR_MARKER = "group chat director"
TRANSCRIPT_MESSAGES = 6
_TEXT_LIMIT = 300
_DESCRIPTION_LIMIT = 120


class _Marker:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


SILENCE = _Marker("SILENCE")
UNDECIDED = _Marker("UNDECIDED")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class SpeakerDirector:
    def __init__(self, ai_provider):
        self.ai_provider = ai_provider

    async def choose(self, messages, members: list[GroupMember], names_by_character_id, user_name):
        """GroupMember, SILENCE or UNDECIDED."""
        if not members:
            return UNDECIDED

        transcript = "\n".join(
            self._line(m, names_by_character_id, user_name)
            for m in messages[-TRANSCRIPT_MESSAGES:]
        )

        try:
            raw = await self.ai_provider.generate_response(
                system_prompt=self._system_prompt(members, user_name),
                messages=[{"role": "user", "content": transcript}],
            )
        except Exception as exc:
            logger.warning("Speaker director call failed: %s", type(exc).__name__)
            return UNDECIDED

        return self._parse(raw, members)

    @staticmethod
    def _line(message, names, user_name) -> str:
        who = user_name if message.sender_type == "user" else names.get(message.sender_character_id, "Someone")
        return f"{who}: {_clip(message.content, _TEXT_LIMIT)}"

    @staticmethod
    def _system_prompt(members, user_name) -> str:
        people = "\n".join(
            f'- slug "{m.slug}": {m.name}'
            + (f" ({_clip(m.description, _DESCRIPTION_LIMIT)})" if m.description else "")
            for m in members
        )
        return (
            f"You are the {DIRECTOR_MARKER}. A user ({user_name}) talks with these characters:\n"
            f"{people}\n\n"
            "Read the conversation and decide who answers the LAST message. "
            "Pick the one character who would most naturally respond. If the "
            "last message answers a question a character asked, that "
            "character replies. Choose nobody (null) only when the message "
            "clearly needs no answer from anyone.\n"
            'Reply with JSON only: {"speaker": "<slug>"} or {"speaker": null}.'
        )

    @staticmethod
    def _parse(raw, members):
        try:
            data = json.loads(_FENCE.sub("", (raw or "").strip()))
        except (ValueError, TypeError):
            logger.warning("Speaker director returned invalid JSON.")
            return UNDECIDED

        if not isinstance(data, dict) or "speaker" not in data:
            return UNDECIDED

        speaker = data["speaker"]
        if speaker is None:
            return SILENCE

        if isinstance(speaker, str):
            for member in members:
                if member.slug == speaker.strip():
                    return member

        logger.warning("Speaker director named an unknown character.")
        return UNDECIDED
