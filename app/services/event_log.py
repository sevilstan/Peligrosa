"""Which commands and buttons a user used, by name only (no message text).

event_name() turns an update into a name from a closed set, so nothing a user
typed can end up in the log: a command is only logged if it is one of ours,
a button only by the short lowercase word its callback starts with.
"""

import re

from aiogram.types import Update

_COMMAND = re.compile(r"^/([A-Za-z_]{1,32})(?:@\w+)?(?:\s|$)")
_BUTTON = re.compile(r"^([a-z]{2,12})(?::|$)")
_IGNORED_BUTTONS = {"noop"}


def event_name(update: Update, known_commands: set[str]) -> str | None:
    message = update.message
    if message is not None and message.text and message.text.startswith("/"):
        found = _COMMAND.match(message.text)
        name = found.group(1).lower() if found else ""
        return f"cmd_{name}" if name in known_commands else "cmd_unknown"

    callback = update.callback_query
    if callback is not None and callback.data:
        found = _BUTTON.match(callback.data)
        if found is None:
            return "btn_other"
        return None if found.group(1) in _IGNORED_BUTTONS else f"btn_{found.group(1)}"
    return None
