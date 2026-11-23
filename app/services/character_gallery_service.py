import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.services.character_definition_loader import CharacterDefinitionLoader

logger = logging.getLogger(__name__)

# One character per page: the gallery is a slider.
PAGE_SIZE = 1


@dataclass(frozen=True)
class GalleryCharacter:
    slug: str
    name: str
    description: str
    avatar_url: str | None = None


@dataclass(frozen=True)
class GalleryPage:
    characters: list[GalleryCharacter]
    page: int  # zero-based, already clamped into range
    total_pages: int

    @property
    def has_previous(self) -> bool:
        return self.page > 0

    @property
    def has_next(self) -> bool:
        return self.page + 1 < self.total_pages


class CharacterGalleryService:
    """Lists the characters a user can talk to.

    Only active characters are ever shown. Name and description come from
    the character's YAML definition when it exists (the platform-managed
    source of truth) and fall back to the database row.
    """

    def __init__(
        self,
        session: AsyncSession,
        definition_loader: CharacterDefinitionLoader | None = None,
        page_size: int = PAGE_SIZE,
    ):
        self.session = session
        self.definition_loader = definition_loader or CharacterDefinitionLoader()
        self.page_size = page_size

    async def get_page(self, page: int) -> GalleryPage:
        total = (
            await self.session.execute(
                select(func.count())
                .select_from(Character)
                .where(Character.is_active.is_(True))
            )
        ).scalar_one()

        total_pages = max(1, -(-total // self.page_size))
        page = min(max(page, 0), total_pages - 1)

        rows = (
            await self.session.execute(
                select(Character)
                .where(Character.is_active.is_(True))
                .order_by(Character.sort_order, Character.name, Character.id)
                .limit(self.page_size)
                .offset(page * self.page_size)
            )
        ).scalars().all()

        return GalleryPage(
            characters=[self.present(row) for row in rows],
            page=page,
            total_pages=total_pages,
        )

    async def get_character(self, slug: str) -> GalleryCharacter | None:
        """Look up one ACTIVE character. The slug comes from a Telegram
        callback, i.e. from the client, so it is never trusted."""
        row = (
            await self.session.execute(
                select(Character).where(
                    Character.slug == slug,
                    Character.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

        return self.present(row) if row else None

    def present(self, row: Character) -> GalleryCharacter:
        definition = None
        try:
            definition = self.definition_loader.load(row.slug)
        except ValueError as exc:
            # A broken YAML must not take the whole gallery down.
            logger.warning(
                "Character definition for '%s' is invalid (%s); using database values.",
                row.slug,
                type(exc).__name__,
            )

        return GalleryCharacter(
            slug=row.slug,
            name=(definition.name if definition else row.name),
            description=(
                (definition.description if definition else "") or row.description
            ),
            avatar_url=row.avatar_url,
        )
