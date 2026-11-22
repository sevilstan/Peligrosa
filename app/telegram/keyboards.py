import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.character_gallery_service import GalleryCharacter, GalleryPage
from app.telegram.texts import t

logger = logging.getLogger(__name__)

GALLERY_PREFIX = "gallery:"
CHARACTER_PREFIX = "char:"
OPEN_PREFIX = "open:"

# Telegram rejects callback_data longer than 64 bytes.
_CALLBACK_LIMIT = 64


def _fits(data: str) -> bool:
    return len(data.encode("utf-8")) <= _CALLBACK_LIMIT


def gallery_keyboard(page: GalleryPage, language: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for character in page.characters:
        data = f"{CHARACTER_PREFIX}{page.page}:{character.slug}"
        if not _fits(data):
            logger.warning("Character slug too long for a Telegram button: %s", character.slug)
            continue
        rows.append([InlineKeyboardButton(text=character.name, callback_data=data)])

    navigation: list[InlineKeyboardButton] = []
    if page.has_previous:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "page_previous"),
                callback_data=f"{GALLERY_PREFIX}{page.page - 1}",
            )
        )
    if page.has_next:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "page_next"),
                callback_data=f"{GALLERY_PREFIX}{page.page + 1}",
            )
        )
    if navigation:
        rows.append(navigation)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def character_card_keyboard(
    character: GalleryCharacter,
    language: str | None,
    back_page: int = 0,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    open_data = f"{OPEN_PREFIX}{character.slug}"
    if _fits(open_data):
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(language, "card_open", name=character.name),
                    callback_data=open_data,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "card_back"),
                callback_data=f"{GALLERY_PREFIX}{back_page}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
