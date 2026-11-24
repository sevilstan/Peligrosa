"""What a character sees when it speaks in a group.

The character's own prompt (identity, personality, rules, ITS memories and the
group summary) is built elsewhere; this adds the group-specific parts. It never
contains another character's memories: it only knows who is in the room and
what was said there.
"""

from app.services.speaker_selection import GroupMember

_DESCRIPTION_LIMIT = 120
DEFAULT_USER_NAME = "User"


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _DESCRIPTION_LIMIT else text[: _DESCRIPTION_LIMIT - 1].rstrip() + "…"


def group_instructions(speaker: GroupMember, members: list[GroupMember], user_name: str) -> str:
    others = [m for m in members if m.id != speaker.id]
    people = "\n".join(
        f"- {m.name}" + (f": {_short(m.description)}" if m.description else "")
        for m in others
    )

    return (
        "GROUP CHAT\n"
        f"You are {speaker.name}, in a group chat with the user ({user_name}) "
        "and these other characters:\n"
        f"{people}\n\n"
        "- Messages from other people are labelled with the speaker's name, "
        'like "Name: text".\n'
        f"- Reply only as {speaker.name}, in the first person. Never write "
        "lines for the user or for other characters, and do not start your "
        "reply with your own name.\n"
        "- You can react to what others said and agree or disagree, in your "
        "own voice. Keep to your own language and length rules."
    )


def label_messages(
    messages,
    speaker_id,
    names_by_character_id: dict,
    user_name: str,
) -> list[dict]:
    """Chat-completion messages from the speaker's point of view.

    The speaker's own earlier lines are "assistant"; everything else is "user"
    and carries the speaker's name, so the model can tell people apart.
    """
    labelled = []

    for message in messages:
        if message.sender_type == "user":
            labelled.append({"role": "user", "content": f"{user_name}: {message.content}"})
        elif message.sender_character_id == speaker_id:
            labelled.append({"role": "assistant", "content": message.content})
        else:
            name = names_by_character_id.get(message.sender_character_id, "Someone")
            labelled.append({"role": "user", "content": f"{name}: {message.content}"})

    return labelled
