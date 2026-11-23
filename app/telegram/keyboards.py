import logging

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.services.chat_session_service import ChatSummary
from app.services.character_gallery_service import GalleryCharacter, GalleryPage
from app.telegram.texts import t

logger = logging.getLogger(__name__)

GALLERY_PREFIX = "gallery:"
OPEN_PREFIX = "open:"
NEW_PREFIX = "new:"
CHAT_PREFIX = "chat:"
NOOP = "noop"

# Telegram rejects callback_data longer than 64 bytes.
_CALLBACK_LIMIT = 64


def _fits(data: str) -> bool:
    return len(data.encode("utf-8")) <= _CALLBACK_LIMIT


def main_menu(language: str | None) -> ReplyKeyboardMarkup:
    """Persistent bottom menu, so the user can always jump around."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t(language, "menu_characters")),
                KeyboardButton(text=t(language, "menu_chats")),
            ]
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def slider_keyboard(page: GalleryPage, language: str | None) -> InlineKeyboardMarkup:
    """‹ 2/5 › under one character, with the chat button below.

    The slider wraps around: ‹ on the first character goes to the last.
    """
    character = page.characters[0]
    rows: list[list[InlineKeyboardButton]] = []

    if page.total_pages > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="‹",
                    callback_data=f"{GALLERY_PREFIX}{(page.page - 1) % page.total_pages}",
                ),
                InlineKeyboardButton(
                    text=t(language, "page_counter", page=page.page + 1, total=page.total_pages),
                    callback_data=NOOP,
                ),
                InlineKeyboardButton(
                    text="›",
                    callback_data=f"{GALLERY_PREFIX}{(page.page + 1) % page.total_pages}",
                ),
            ]
        )

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
    else:
        logger.warning("Character slug too long for a Telegram button: %s", character.slug)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def new_chat_keyboard(character: GalleryCharacter, language: str | None) -> InlineKeyboardMarkup | None:
    data = f"{NEW_PREFIX}{character.slug}"
    if not _fits(data):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_new_chat", name=character.name),
                    callback_data=data,
                )
            ]
        ]
    )


def chats_keyboard(chats: list[ChatSummary]) -> InlineKeyboardMarkup:
    rows = []
    for chat in chats:
        marker = "● " if chat.is_active else ""
        date = chat.created_at.strftime("%Y-%m-%d") if chat.created_at else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker}{chat.character.name} · {date}".strip(" ·"),
                    callback_data=f"{CHAT_PREFIX}{chat.conversation_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
