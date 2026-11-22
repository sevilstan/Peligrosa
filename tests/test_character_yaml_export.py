from types import SimpleNamespace

from scripts.export_characters_to_yaml import build_yaml_data


def test_exporter_preserves_existing_character_profile_fields():
    character = SimpleNamespace(
        name="Elena",
        slug="elena",
        description="Gizemli ve zeki.",
        personality="Esprili, meraklı ve sıcak.",
        system_prompt="Stay in character.",
    )

    data = build_yaml_data(character)

    assert data["name"] == "Elena"
    assert data["slug"] == "elena"
    assert data["description"] == "Gizemli ve zeki."
    assert data["personality"] == {
        "existing_profile": ["Esprili, meraklı ve sıcak."]
    }
    assert data["system_prompt"] == "Stay in character."


def test_exporter_keeps_empty_personality_empty():
    character = SimpleNamespace(
        name="Elena",
        slug="elena",
        description="",
        personality=" ",
        system_prompt="",
    )

    data = build_yaml_data(character)

    assert data["personality"] == {}
