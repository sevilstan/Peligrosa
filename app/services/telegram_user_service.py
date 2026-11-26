import re

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

DEFAULT_LANGUAGE = "en"
_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}")
_DISPLAY_NAME_MAX = 100


def normalize_language_code(code: str | None) -> str:
    """Reduce a Telegram language_code ("pt-br", "tr") to its primary subtag.

    users.language_code is VARCHAR(5) NOT NULL, and Telegram may send
    nothing or something longer, so always return a safe value.
    """
    if not code:
        return DEFAULT_LANGUAGE

    match = _LANGUAGE_PATTERN.match(code.strip().lower())
    return match.group(0) if match else DEFAULT_LANGUAGE


_NAME_PATTERN = re.compile(r"^[\w .'\-]{1,40}$")


def clean_name(raw: str | None) -> str | None:
    """A name the user typed, or None when it is not a plausible name.

    The name goes into AI prompts, so only letters, digits, spaces and . ' -
    are accepted (no newlines or instructions), at most 40 characters.
    """
    name = " ".join((raw or "").split())
    if not name or name.startswith("/") or not _NAME_PATTERN.match(name):
        return None
    return name


def build_display_name(
    first_name: str | None,
    last_name: str | None = None,
) -> str | None:
    name = " ".join(part for part in (first_name, last_name) if part).strip()
    return name[:_DISPLAY_NAME_MAX] or None


class TelegramUserService:
    """Maps a Telegram account to a platform user."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(
        self,
        telegram_id: int,
        first_name: str | None = None,
        last_name: str | None = None,
        language_code: str | None = None,
    ) -> User:
        display_name = build_display_name(first_name, last_name)
        language = normalize_language_code(language_code)

        # Atomic: two simultaneous updates for a new user must not crash on
        # the unique telegram_id constraint, so let the database arbitrate.
        await self.session.execute(
            pg_insert(User)
            .values(
                telegram_id=telegram_id,
                display_name=display_name,
                language_code=language,
                is_active=True,
            )
            .on_conflict_do_nothing(index_elements=["telegram_id"])
        )

        user = (
            await self.session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
        ).scalar_one()

        # Keep profile data fresh without ever touching is_active.
        changes = {}
        if display_name and user.name_status != "custom" and user.display_name != display_name:
            changes["display_name"] = display_name
        if language_code and user.language_code != language:
            changes["language_code"] = language

        if changes:
            await self.session.execute(
                update(User).where(User.id == user.id).values(**changes)
            )
            for key, value in changes.items():
                setattr(user, key, value)

        await self.session.commit()
        return user


    async def mark_name_asked(self, user: User) -> None:
        """Remember that the name question was shown (it is asked only once)."""
        if user.name_status == "unasked":
            await self.session.execute(
                update(User).where(User.id == user.id).values(name_status="asked")
            )
            await self.session.commit()
            user.name_status = "asked"

    async def set_custom_name(self, user: User, raw: str | None) -> str | None:
        """Save the name the user chose; None when it is not acceptable."""
        name = clean_name(raw)
        if name is None:
            return None
        await self.session.execute(
            update(User)
            .where(User.id == user.id)
            .values(display_name=name, name_status="custom")
        )
        await self.session.commit()
        user.display_name = name
        user.name_status = "custom"
        return name
