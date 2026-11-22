import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.character_gallery_service import (
    CharacterGalleryService,
    GalleryCharacter,
)
from app.telegram.keyboards import (
    CHARACTER_PREFIX,
    GALLERY_PREFIX,
    OPEN_PREFIX,
    character_card_keyboard,
    gallery_keyboard,
)
from app.telegram.texts import t

logger = logging.getLogger(__name__)

_SNIPPET_LENGTH = 110
_CARD_DESCRIPTION_LIMIT = 1500


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def _gallery_view(session: AsyncSession, language: str, page: int):
    gallery = await CharacterGalleryService(session).get_page(page)

    if not gallery.characters:
        return t(language, "gallery_empty"), None

    lines = [t(language, "gallery_title", page=gallery.page + 1, total=gallery.total_pages), ""]
    for character in gallery.characters:
        name = html.escape(character.name)
        snippet = html.escape(_shorten(character.description, _SNIPPET_LENGTH))
        lines.append(f"<b>{name}</b> — {snippet}" if snippet else f"<b>{name}</b>")

    return "\n".join(lines), gallery_keyboard(gallery, language)


def _card_text(character: GalleryCharacter) -> str:
    name = html.escape(character.name)
    description = html.escape(_shorten(character.description, _CARD_DESCRIPTION_LIMIT))
    return f"<b>{name}</b>\n\n{description}" if description else f"<b>{name}</b>"


async def _edit(callback: CallbackQuery, text: str, markup) -> None:
    """Edit the message under a button; ignore a no-op edit."""
    message = callback.message
    if message is None or not hasattr(message, "edit_text"):
        return  # inaccessible (old) message: nothing to edit
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def start(message: Message, session: AsyncSession, user: User) -> None:
    language = user.language_code
    name = f", {html.escape(user.display_name)}" if user.display_name else ""
    text, markup = await _gallery_view(session, language, 0)
    await message.answer(t(language, "welcome", name=name))
    await message.answer(text, reply_markup=markup)


async def characters(message: Message, session: AsyncSession, user: User) -> None:
    text, markup = await _gallery_view(session, user.language_code, 0)
    await message.answer(text, reply_markup=markup)


async def gallery_page(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    raw = callback.data.removeprefix(GALLERY_PREFIX)
    page = int(raw) if raw.isdecimal() and len(raw) < 6 else 0

    text, markup = await _gallery_view(session, user.language_code, page)
    await _edit(callback, text, markup)
    await callback.answer()


async def character_card(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    language = user.language_code
    page_raw, _, slug = callback.data.removeprefix(CHARACTER_PREFIX).partition(":")
    back_page = int(page_raw) if page_raw.isdecimal() and len(page_raw) < 6 else 0

    # The slug comes from the client: look it up, never trust it.
    character = await CharacterGalleryService(session).get_character(slug)
    if character is None:
        await callback.answer(t(language, "character_missing"), show_alert=True)
        return

    await _edit(callback, _card_text(character), character_card_keyboard(character, language, back_page))
    await callback.answer()


async def open_chat(callback: CallbackQuery, user: User) -> None:
    # Chat wiring is the next roadmap step (Personal Chat).
    await callback.answer(t(user.language_code, "chat_soon"), show_alert=True)


async def plain_text(message: Message, user: User) -> None:
    await message.answer(t(user.language_code, "plain_text"))


def build_router() -> Router:
    """A fresh router per dispatcher (a router can only be attached once)."""
    router = Router(name="foundation")

    router.message.register(start, Command("start"))
    router.message.register(characters, Command("characters"))
    router.callback_query.register(gallery_page, F.data.startswith(GALLERY_PREFIX))
    router.callback_query.register(character_card, F.data.startswith(CHARACTER_PREFIX))
    router.callback_query.register(open_chat, F.data.startswith(OPEN_PREFIX))
    # Registered last: commands above must win over the plain-text fallback.
    router.message.register(plain_text, F.text)

    return router
