"""Make the database know every character that has a YAML file.

The gallery only lists characters that exist as ACTIVE rows in the database
(conversations, memories and messages point to those rows), while the YAML
files in characters/ hold the character itself. Adding a YAML file alone
therefore shows nothing in Telegram: this service creates the missing rows and
keeps the text fields in step with the files.

Rules:
- the file name is the slug; a new slug gets a new active row, placed after the
  existing ones in file-name order;
- an existing row only gets its text fields refreshed (name, description,
  personality text, system prompt). Whether it is active, its position and its
  avatar_url are the operator's decisions and are never touched;
- a broken file is reported and skipped, it never blocks the other characters;
- nothing is ever deleted (a removed YAML file does not remove a character).
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.services.character_definition_loader import CharacterDefinitionLoader

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # slug -> reason


def personality_text(personality) -> str:
    """A compact text version for the database column (the YAML itself is
    what the prompt uses)."""
    items = []
    for section in ("core_traits",):
        items.extend(personality.get(section, ()))
    if not items:
        for values in personality.values():
            items.extend(values)
    return "; ".join(items)


class CharacterSyncService:
    def __init__(self, session: AsyncSession, loader: CharacterDefinitionLoader | None = None):
        self.session = session
        self.loader = loader or CharacterDefinitionLoader()

    async def sync(self) -> SyncResult:
        result = SyncResult()

        existing = {
            row.slug: row for row in (await self.session.execute(select(Character))).scalars()
        }
        next_order = (
            await self.session.execute(select(func.coalesce(func.max(Character.sort_order), -1)))
        ).scalar_one() + 1

        for path in sorted(self.loader.characters_dir.glob("*.yaml")):
            slug = path.stem
            try:
                definition = self.loader.load(slug)
            except ValueError as exc:
                # Only the message of OUR validation errors: it names the file
                # and the field, never user data.
                result.failed[slug] = str(exc)
                logger.warning("Character '%s' skipped: %s", slug, exc)
                continue

            if definition is None:
                continue

            values = {
                "name": definition.name,
                "description": definition.description,
                "personality": personality_text(definition.personality),
                "system_prompt": definition.system_prompt,
            }

            row = existing.get(slug)

            if row is None:
                self.session.add(
                    Character(slug=slug, is_active=True, sort_order=next_order, **values)
                )
                next_order += 1
                result.created.append(slug)
            elif any(getattr(row, key) != value for key, value in values.items()):
                for key, value in values.items():
                    setattr(row, key, value)
                result.updated.append(slug)
            else:
                result.unchanged.append(slug)

        await self.session.commit()

        logger.info(
            "Characters synced: %d created, %d updated, %d unchanged, %d failed.",
            len(result.created),
            len(result.updated),
            len(result.unchanged),
            len(result.failed),
        )
        return result
