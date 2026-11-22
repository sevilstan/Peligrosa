"""Export existing database character profiles to YAML without overwriting files.

Run from the project root:
    python -m scripts.export_characters_to_yaml

Use --overwrite only when you intentionally want database values to replace
existing YAML files.
"""

import argparse
import asyncio
from pathlib import Path
import re

import yaml
from sqlalchemy import select

from app.database.session import SessionLocal, engine
from app.models.character import Character


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHARACTERS_DIR = PROJECT_ROOT / "characters"


def build_yaml_data(character: Character) -> dict:
    """Convert the existing DB profile into the initial YAML structure."""
    personality = (character.personality or "").strip()

    return {
        "name": character.name,
        "slug": character.slug,
        "description": character.description or "",
        "personality": (
            {"existing_profile": [personality]} if personality else {}
        ),
        "system_prompt": character.system_prompt or "",
    }


async def export_characters(overwrite: bool = False) -> tuple[int, int]:
    if SessionLocal is None or engine is None:
        raise RuntimeError(
            "Database is not configured. Check DATABASE_URL in your local .env."
        )

    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    created = 0
    skipped = 0

    async with SessionLocal() as session:
        result = await session.execute(select(Character).order_by(Character.slug))
        characters = result.scalars().all()

        for character in characters:
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", character.slug):
                raise ValueError(f"Unsafe character slug: {character.slug!r}")

            output_path = CHARACTERS_DIR / f"{character.slug}.yaml"

            if output_path.exists() and not overwrite:
                print(f"Skipped (already exists): {output_path.name}")
                skipped += 1
                continue

            data = build_yaml_data(character)
            output_path.write_text(
                yaml.safe_dump(
                    data,
                    allow_unicode=True,
                    sort_keys=False,
                    width=100,
                ),
                encoding="utf-8",
            )
            print(f"Exported: {output_path.name}")
            created += 1

    await engine.dispose()
    return created, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Export database character profiles to YAML."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing YAML files with current database values.",
    )
    args = parser.parse_args()

    created, skipped = asyncio.run(export_characters(overwrite=args.overwrite))
    print(f"Finished. Exported: {created}, skipped: {skipped}")


if __name__ == "__main__":
    main()
