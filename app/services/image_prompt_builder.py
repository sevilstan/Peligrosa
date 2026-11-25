"""Turn a character and a scene into one image prompt.

The character's look comes ONLY from the YAML `appearance` text, and the
character is always an adult with a stated age. The scene comes from the
user's chat, so it is untrusted text: it is cleaned and shortened, and it can
never change who is drawn.
"""

import re

MAX_SCENE_CHARS = 300

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class ImageNotAvailable(ValueError):
    """This character has no appearance (or no adult age) to draw from."""


def clean_scene(scene: str | None) -> str:
    text = " ".join(_CONTROL.sub(" ", scene or "").split())
    return text[:MAX_SCENE_CHARS]


def build_image_prompt(definition, scene: str | None = None) -> str:
    age = definition.profile.age if definition.profile else None
    if not definition.appearance or age is None:
        raise ImageNotAvailable(definition.slug)

    parts = [
        f"A realistic photo of {definition.name}, a fictional adult aged {age}.",
        f"Appearance: {definition.appearance}",
    ]

    scene = clean_scene(scene)
    if scene:
        parts.append(f"Situation (from the chat, only the setting and mood): {scene}")
    else:
        parts.append("A natural, casual photo of her.")

    parts.append(
        "She keeps the same face and look as described. Not a real person, "
        "no celebrity likeness, no text or logos in the image."
    )
    return "\n".join(parts)
