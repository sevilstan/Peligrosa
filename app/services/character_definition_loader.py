from dataclasses import dataclass
from pathlib import Path
import re
from typing import Mapping

import yaml


_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class CharacterDefinition:
    """Static, platform-managed character data loaded from YAML."""

    name: str
    slug: str
    description: str
    personality: Mapping[str, tuple[str, ...]]
    system_prompt: str


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

        return CharacterDefinition(
            name=name,
            slug=file_slug,
            description=description,
            personality=personality,
            system_prompt=system_prompt,
        )

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
