from dataclasses import dataclass
from pathlib import Path
import re
from typing import Mapping

import yaml


_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


MIN_AGE = 18  # every character is an adult
MAX_AGE = 120
_SHORT_LIMIT = 60
_BIO_LIMIT = 600
_HIGHLIGHT_LIMIT = 40
_APPEARANCE_LIMIT = 500
MAX_HIGHLIGHTS = 5


@dataclass(frozen=True)
class CharacterProfile:
    """The facts shown on a character's card (and known to the character)."""

    age: int | None = None
    city: str = ""
    occupation: str = ""
    bio: str = ""  # a short life story
    highlights: tuple[str, ...] = ()  # a few key traits, one or two words each

    @property
    def is_empty(self) -> bool:
        return not (self.age or self.city or self.occupation or self.bio or self.highlights)


@dataclass(frozen=True)
class CharacterDefinition:
    """Static, platform-managed character data loaded from YAML."""

    name: str
    slug: str
    description: str
    personality: Mapping[str, tuple[str, ...]]
    system_prompt: str
    profile: CharacterProfile | None = None
    # How the character looks (hair, eyes, style...). Used only to draw her;
    # without it no picture can be made, so a face is never invented.
    appearance: str = ""


class CharacterDefinitionLoader:
    """Loads one character definition from characters/<slug>.yaml.

    Missing files return None so existing database-backed characters keep
    working during the gradual migration to YAML. Invalid YAML is an error:
    silently falling back would hide a broken character definition.
    """

    def __init__(self, characters_dir: Path | str | None = None):
        self.characters_dir = (
            Path(characters_dir)
            if characters_dir is not None
            else Path(__file__).resolve().parents[2] / "characters"
        )

    def load(self, slug: str) -> CharacterDefinition | None:
        if not isinstance(slug, str) or not _SLUG_PATTERN.fullmatch(slug):
            raise ValueError("Invalid character slug.")

        path = self.characters_dir / f"{slug}.yaml"
        if not path.is_file():
            return None

        try:
            with path.open("r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML for character '{slug}'.") from exc

        if not isinstance(data, dict):
            raise ValueError(f"Character definition '{slug}' must be a YAML mapping.")

        name = self._required_text(data, "name", slug)
        file_slug = self._required_text(data, "slug", slug)
        description = self._optional_text(data, "description", slug)
        system_prompt = self._optional_text(data, "system_prompt", slug)
        personality = self._parse_personality(data.get("personality", {}), slug)

        if file_slug != slug:
            raise ValueError(
                f"Character slug mismatch: requested '{slug}', "
                f"but YAML declares '{file_slug}'."
            )

        profile = self._parse_profile(data.get("profile"), slug)
        appearance = self._profile_text(
            data.get("appearance"), "appearance", slug, _APPEARANCE_LIMIT
        )
        if appearance and (profile is None or profile.age is None):
            # Pictures are only drawn of adults: the age must be stated (18+
            # is enforced by the profile parser).
            raise ValueError(
                f"Character '{slug}' has an appearance but no profile age; "
                "pictures need a stated adult age."
            )

        return CharacterDefinition(
            name=name,
            slug=file_slug,
            description=description,
            personality=personality,
            system_prompt=system_prompt,
            profile=profile,
            appearance=appearance,
        )

    @staticmethod
    def _profile_text(value: object, key: str, slug: str, limit: int) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError(f"Character '{slug}' profile field '{key}' must be a string.")
        value = " ".join(value.split())
        if len(value) > limit:
            raise ValueError(
                f"Character '{slug}' profile field '{key}' is longer than {limit} characters."
            )
        return value

    @classmethod
    def _parse_profile(cls, value: object, slug: str) -> CharacterProfile | None:
        """Optional `profile:` block: age, city, occupation, bio, highlights.

        Unknown keys are ignored (room to grow); wrong types, an age under 18
        and over-long texts are errors, like everything else in the file.
        """
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"Character '{slug}' field 'profile' must be a mapping.")

        age = value.get("age")
        if age is not None:
            if isinstance(age, bool) or not isinstance(age, int) or not MIN_AGE <= age <= MAX_AGE:
                raise ValueError(
                    f"Character '{slug}' profile age must be a whole number from {MIN_AGE} to {MAX_AGE}."
                )

        highlights = value.get("highlights", [])
        if highlights is None:
            highlights = []
        if (
            not isinstance(highlights, list)
            or len(highlights) > MAX_HIGHLIGHTS
            or not all(isinstance(item, str) and item.strip() for item in highlights)
        ):
            raise ValueError(
                f"Character '{slug}' profile highlights must be a list of at most "
                f"{MAX_HIGHLIGHTS} non-empty strings."
            )

        profile = CharacterProfile(
            age=age,
            city=cls._profile_text(value.get("city"), "city", slug, _SHORT_LIMIT),
            occupation=cls._profile_text(value.get("occupation"), "occupation", slug, _SHORT_LIMIT),
            bio=cls._profile_text(value.get("bio"), "bio", slug, _BIO_LIMIT),
            highlights=tuple(
                cls._profile_text(item, "highlights", slug, _HIGHLIGHT_LIMIT) for item in highlights
            ),
        )
        return None if profile.is_empty else profile

    @staticmethod
    def _required_text(data: dict, key: str, slug: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Character '{slug}' requires a non-empty '{key}' field."
            )
        return value.strip()

    @staticmethod
    def _optional_text(data: dict, key: str, slug: str) -> str:
        value = data.get(key, "")
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError(
                f"Character '{slug}' field '{key}' must be a string."
            )
        return value.strip()

    @staticmethod
    def _parse_personality(value: object, slug: str) -> dict[str, tuple[str, ...]]:
        if not isinstance(value, dict):
            raise ValueError(
                f"Character '{slug}' field 'personality' must be a mapping."
            )

        parsed: dict[str, tuple[str, ...]] = {}
        for section, items in value.items():
            if not isinstance(section, str) or not section.strip():
                raise ValueError(
                    f"Character '{slug}' has an invalid personality section."
                )
            if not isinstance(items, list) or not all(
                isinstance(item, str) and item.strip() for item in items
            ):
                raise ValueError(
                    f"Character '{slug}' personality section '{section}' "
                    "must contain a list of non-empty strings."
                )
            parsed[section.strip()] = tuple(item.strip() for item in items)

        return parsed
