"""Who answers when nobody was addressed by name? One small AI call.

The rules in speaker_selection settle the clear cases (addressed by name) for
free. For the rest the director reads the last few messages and returns the
characters who would naturally answer, in reply order: usually everyone, fewer
when some have nothing to say, and nobody (silence) only when no answer is
needed.

Model output is untrusted: only slugs of real members are accepted (repeats and
unknown slugs are dropped). Any failure (provider error, invalid JSON, no valid
slug) returns UNDECIDED and the caller falls back to "everyone answers", so a
reply is never lost.
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
        """A list of GroupMembers (reply order), SILENCE or UNDECIDED."""
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
            "Read the conversation and decide who answers the LAST message, "
            "in the order they reply. In a group chat people usually react "
            "together: include every character who would have something to "
            "say, and leave out only those who clearly would not. If the "
            "last message answers a question a character asked, that "
            "character replies first. Use an empty list only when the "
            "message needs no answer from anyone.\n"
            'Reply with JSON only: {"speakers": ["<slug>", ...]}.'
        )

    @staticmethod
    def _parse(raw, members):
        try:
            data = json.loads(_FENCE.sub("", (raw or "").strip()))
        except (ValueError, TypeError):
            logger.warning("Speaker director returned invalid JSON.")
            return UNDECIDED

        if not isinstance(data, dict) or not isinstance(data.get("speakers"), list):
            return UNDECIDED

        by_slug = {m.slug: m for m in members}
        chosen: list[GroupMember] = []

        for slug in data["speakers"]:
            member = by_slug.get(slug.strip()) if isinstance(slug, str) else None
            if member is not None and member not in chosen:
                chosen.append(member)

        if chosen:
            return chosen

        if not data["speakers"]:
            return SILENCE

        logger.warning("Speaker director named no known character.")
        return UNDECIDED
