"""YAML files become database characters (so the Telegram gallery shows them)."""

import logging
from pathlib import Path

from sqlalchemy import select

from app.models import Character
from app.services.character_definition_loader import CharacterDefinitionLoader
from app.services.character_gallery_service import CharacterGalleryService
from app.services.character_sync_service import CharacterSyncService
from app.telegram.avatars import AvatarProvider


def write(directory, slug, name=None, description="Kısa tanım.", extra=""):
    (directory / f"{slug}.yaml").write_text(
        f"name: {name or slug.title()}\nslug: {slug}\ndescription: {description}\n"
        "system_prompt: Sen bir karaktersin.\n"
        "personality:\n  core_traits:\n    - Esprili\n    - Merakli\n" + extra,
        encoding="utf-8",
    )


async def sync(maker, directory):
    async with maker() as s:
        return await CharacterSyncService(s, CharacterDefinitionLoader(directory)).sync()


async def rows(maker):
    async with maker() as s:
        return {
            c.slug: c
            for c in (await s.execute(select(Character))).scalars()
        }


def test_new_yaml_files_become_active_characters_the_gallery_shows(run_db, tmp_path):
    write(tmp_path, "elena", "Elena")
    write(tmp_path, "defne", "Defne")
    write(tmp_path, "lara", "Lara")

    async def scenario(maker):
        result = await sync(maker, tmp_path)
        assert sorted(result.created) == ["defne", "elena", "lara"]
        assert result.failed == {}

        data = await rows(maker)
        assert data["defne"].is_active is True
        assert data["defne"].personality == "Esprili; Merakli"
        assert data["defne"].system_prompt == "Sen bir karaktersin."
        assert sorted(c.sort_order for c in data.values()) == [0, 1, 2]

        async with maker() as s:
            page = await CharacterGalleryService(s, CharacterDefinitionLoader(tmp_path), page_size=10).get_page(0)
        assert sorted(c.slug for c in page.characters) == ["defne", "elena", "lara"]

    run_db(scenario)


def test_sync_is_idempotent(run_db, tmp_path):
    write(tmp_path, "elena")

    async def scenario(maker):
        await sync(maker, tmp_path)
        second = await sync(maker, tmp_path)
        assert second.created == [] and second.updated == []
        assert second.unchanged == ["elena"]
        assert len(await rows(maker)) == 1

    run_db(scenario)


def test_new_character_goes_after_existing_ones(run_db, tmp_path):
    write(tmp_path, "elena")

    async def scenario(maker):
        await sync(maker, tmp_path)
        async with maker() as s:
            (await s.execute(select(Character))).scalar_one().sort_order = 7
            await s.commit()
        write(tmp_path, "defne")
        await sync(maker, tmp_path)
        data = await rows(maker)
        assert data["elena"].sort_order == 7
        assert data["defne"].sort_order == 8

    run_db(scenario)


def test_changed_text_is_updated(run_db, tmp_path):
    write(tmp_path, "elena", description="Eski.")

    async def scenario(maker):
        await sync(maker, tmp_path)
        write(tmp_path, "elena", description="Yeni.")
        result = await sync(maker, tmp_path)
        assert result.updated == ["elena"]
        assert (await rows(maker))["elena"].description == "Yeni."

    run_db(scenario)


def test_operator_decisions_are_never_overwritten(run_db, tmp_path):
    write(tmp_path, "elena", description="Eski.")

    async def scenario(maker):
        await sync(maker, tmp_path)
        async with maker() as s:
            row = (await s.execute(select(Character))).scalar_one()
            row.is_active = False
            row.sort_order = 42
            row.avatar_url = "https://example.com/a.png"
            await s.commit()

        write(tmp_path, "elena", description="Yeni.")
        await sync(maker, tmp_path)

        row = (await rows(maker))["elena"]
        assert row.description == "Yeni."
        assert row.is_active is False
        assert row.sort_order == 42
        assert row.avatar_url == "https://example.com/a.png"

    run_db(scenario)


def test_broken_file_is_skipped_and_others_still_sync(run_db, tmp_path, caplog):
    write(tmp_path, "elena")
    (tmp_path / "broken.yaml").write_text("name: [unclosed\n", encoding="utf-8")
    (tmp_path / "wrongslug.yaml").write_text(
        "name: X\nslug: other\ndescription: d\n", encoding="utf-8"
    )

    async def scenario(maker):
        with caplog.at_level(logging.WARNING):
            result = await sync(maker, tmp_path)
        assert result.created == ["elena"]
        assert sorted(result.failed) == ["broken", "wrongslug"]
        assert list(await rows(maker)) == ["elena"]

    run_db(scenario)


def test_template_and_other_extensions_are_ignored(run_db, tmp_path):
    write(tmp_path, "elena")
    (tmp_path / "_template.yaml.example").write_text("name: T\nslug: _template\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")

    async def scenario(maker):
        result = await sync(maker, tmp_path)
        assert result.created == ["elena"] and result.failed == {}

    run_db(scenario)


def test_repository_characters_sync_and_have_avatars(run_db):
    """The real characters/ folder: every YAML syncs, and every synced
    character has a photo file named after its slug."""
    characters_dir = Path(__file__).resolve().parents[1] / "characters"
    slugs = sorted(p.stem for p in characters_dir.glob("*.yaml"))
    assert slugs, "characters/ must contain at least one YAML file"

    async def scenario(maker):
        result = await sync(maker, characters_dir)
        assert result.failed == {}
        assert sorted(await rows(maker)) == slugs

    run_db(scenario)

    for slug in slugs:
        assert AvatarProvider().resolve(slug, None) is not None, slug


def test_start_up_sync_never_stops_the_bot(caplog):
    import asyncio

    from app.telegram.bot import sync_characters_on_start

    def broken_maker():
        raise ConnectionError("db down")

    with caplog.at_level(logging.ERROR):
        asyncio.run(sync_characters_on_start(broken_maker))  # must not raise

    assert "ConnectionError" in caplog.text
    assert "db down" not in caplog.text
