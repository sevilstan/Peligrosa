"""Who answers in a group? Rules only, no AI call.

Step B of the group design has exactly one speaker per user message. The
director call that lets several characters speak "when they have something to
say" replaces the fallback rules later (step C); the addressing rules stay.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GroupMember:
    id: object
    slug: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class SpeakerChoice:
    member: GroupMember
    reason: str  # "addressed", "continuation" or "default"


def _name_tokens(member: GroupMember) -> list[str]:
    """What users call a character: full name, first name, slug."""
    tokens = [member.name.strip()]

    first = member.name.strip().split(" ")[0]
    if len(first) >= 3:
        tokens.append(first)

    if member.slug:
        tokens.append(member.slug)

    seen: list[str] = []
    for token in tokens:
        if token and token.casefold() not in (s.casefold() for s in seen):
            seen.append(token)
    return seen


def _earliest(patterns: list[str], text: str) -> int | None:
    positions = [
        m.start()
        for pattern in patterns
        if (m := re.search(pattern, text, re.IGNORECASE))
    ]
    return min(positions) if positions else None


def _strong_patterns(token: str) -> list[str]:
    t = re.escape(token)
    return [
        rf"@{t}(?!\w)",  # @Elena
        rf"^\W*{t}(?!\w)",  # "Elena, ..." / "Elena nasılsın"
        rf"(?<!\w){t}\s*[,:]",  # "..., Elena: ..."
        rf",\s*{t}\W*$",  # "what do you think, Elena?"
    ]


def _weak_patterns(token: str) -> list[str]:
    return [rf"(?<!\w){re.escape(token)}(?!\w)"]


def _first_addressed(text: str, members: list[GroupMember], patterns_for) -> GroupMember | None:
    best: tuple[int, int] | None = None
    chosen = None

    for order, member in enumerate(members):
        patterns = [p for token in _name_tokens(member) for p in patterns_for(token)]
        position = _earliest(patterns, text)
        if position is None:
            continue
        if best is None or (position, order) < best:
            best, chosen = (position, order), member

    return chosen


def select_speaker(
    text: str,
    members: list[GroupMember],
    last_speaker_id=None,
) -> SpeakerChoice:
    """Pick the one character who answers this message.

    1. A character spoken to directly ("Elena, ...", "@Elena", "..., Elena?").
    2. A character merely mentioned by name (the first one in the text).
    3. The character who spoke last (the user is probably answering them).
    4. The first member (deterministic).

    Names inside longer words never count; matching ignores case.
    """
    if not members:
        raise ValueError("A group needs at least one member.")

    addressed = _first_addressed(text, members, _strong_patterns) or _first_addressed(
        text, members, _weak_patterns
    )
    if addressed is not None:
        return SpeakerChoice(addressed, "addressed")

    for member in members:
        if last_speaker_id is not None and member.id == last_speaker_id:
            return SpeakerChoice(member, "continuation")

    return SpeakerChoice(members[0], "default")
