from pathlib import Path

import pytest

from app.services.character_definition_loader import CharacterDefinitionLoader


def write_character(directory: Path, content: str, filename: str = "elena.yaml"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(content, encoding="utf-8")


def test_loads_structured_character_definition(tmp_path):
    write_character(
        tmp_path,
        """
name: Elena
slug: elena
description: Gizemli ve zeki.
personality:
  core_traits:
    - Esprili
    - Meraklı
  speech_style:
    - Doğal konuşur
system_prompt: |
  You are Elena. Stay in character.
""",
    )

    definition = CharacterDefinitionLoader(tmp_path).load("elena")

    assert definition is not None
    assert definition.name == "Elena"
    assert definition.slug == "elena"
    assert definition.description == "Gizemli ve zeki."
    assert definition.personality["core_traits"] == ("Esprili", "Meraklı")
    assert definition.personality["speech_style"] == ("Doğal konuşur",)
    assert "Stay in character" in definition.system_prompt


def test_missing_yaml_returns_none_for_legacy_database_fallback(tmp_path):
    assert CharacterDefinitionLoader(tmp_path).load("elena") is None


def test_rejects_invalid_slug_and_path_traversal(tmp_path):
    loader = CharacterDefinitionLoader(tmp_path)

    with pytest.raises(ValueError, match="Invalid character slug"):
        loader.load("../secrets")


def test_rejects_slug_mismatch(tmp_path):
    write_character(
        tmp_path,
        "name: Elena\nslug: natalie\ndescription: Test\n",
    )

    with pytest.raises(ValueError, match="slug mismatch"):
        CharacterDefinitionLoader(tmp_path).load("elena")


def test_rejects_invalid_personality_shape(tmp_path):
    write_character(
        tmp_path,
        """
name: Elena
slug: elena
personality:
  core_traits: Esprili
""",
    )

    with pytest.raises(ValueError, match="must contain a list"):
        CharacterDefinitionLoader(tmp_path).load("elena")


def test_rejects_malformed_yaml(tmp_path):
    write_character(tmp_path, "name: Elena\nslug: [elena\n")

    with pytest.raises(ValueError, match="Invalid YAML"):
        CharacterDefinitionLoader(tmp_path).load("elena")
