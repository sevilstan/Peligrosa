import logging

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import uuid

from app.services.chat_session_service import ChatListPage, HistoryPage
from app.services.character_gallery_service import GalleryCharacter, GalleryPage
from app.telegram.texts import t

logger = logging.getLogger(__name__)

GALLERY_PREFIX = "gallery:"
OPEN_PREFIX = "open:"
NEW_PREFIX = "new:"
CHAT_PREFIX = "chat:"
CHATS_PAGE_PREFIX = "chats:"
GROUP_NEW = "gnew"
GROUP_SELECT_PREFIX = "gsel:"
GROUP_PAGE_PREFIX = "gpage:"
GROUP_DONE = "gdone"
GROUP_CANCEL = "gcancel"
HISTORY_OPEN_PREFIX = "hopen:"  # from a chat message: send history as a new message
HISTORY_PAGE_PREFIX = "hist:"  # from the history itself: edit it in place
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
                KeyboardButton(text=t(language, "menu_history")),
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


def chat_actions_keyboard(
    character: GalleryCharacter,
    conversation_id: uuid.UUID,
    language: str | None,
    is_group: bool = False,
) -> InlineKeyboardMarkup | None:
    """Under a chat message: see its history, or start a fresh chat."""
    row = [
        InlineKeyboardButton(
            text=t(language, "btn_history"),
            callback_data=f"{HISTORY_OPEN_PREFIX}{conversation_id}",
        )
    ]

    new_data = f"{NEW_PREFIX}{character.slug}"
    if not is_group and _fits(new_data):
        row.append(
            InlineKeyboardButton(
                text=t(language, "btn_new_chat", name=character.name),
                callback_data=new_data,
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[row])


def _page_navigation(
    prefix: str, language: str | None, previous_page: int | None, next_page: int | None,
    page: int, total: int, previous_key: str, next_key: str,
) -> list[InlineKeyboardButton]:
    if total <= 1:
        return []
    row = []
    if previous_page is not None:
        row.append(InlineKeyboardButton(text=t(language, previous_key), callback_data=f"{prefix}{previous_page}"))
    row.append(
        InlineKeyboardButton(
            text=t(language, "page_counter", page=page + 1, total=total), callback_data=NOOP
        )
    )
    if next_page is not None:
        row.append(InlineKeyboardButton(text=t(language, next_key), callback_data=f"{prefix}{next_page}"))
    return row


def chats_keyboard(page: ChatListPage, language: str | None) -> InlineKeyboardMarkup:
    rows = []
    for chat in page.items:
        marker = "● " if chat.is_active else ""
        date = chat.created_at.strftime("%Y-%m-%d") if chat.created_at else ""
        icon = "👥 " if chat.is_group else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker}{icon}{chat.name} · {date}".strip(" ·"),
                    callback_data=f"{CHAT_PREFIX}{chat.conversation_id}",
                )
            ]
        )

    navigation = _page_navigation(
        CHATS_PAGE_PREFIX, language,
        previous_page=page.page - 1 if page.page > 0 else None,
        next_page=page.page + 1 if page.page + 1 < page.total_pages else None,
        page=page.page, total=page.total_pages,
        previous_key="page_previous", next_key="page_next",
    )
    if navigation:
        rows.append(navigation)
    rows.append(new_group_row(language))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def new_group_row(language: str | None) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=t(language, "btn_new_group"), callback_data=GROUP_NEW)]


def new_group_keyboard(language: str | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[new_group_row(language)])


def group_picker_keyboard(
    page: GalleryPage, selected: list[str], language: str | None
) -> InlineKeyboardMarkup:
    """Tick characters (✓), page through them, then create or cancel."""
    rows = []
    for character in page.characters:
        data = f"{GROUP_SELECT_PREFIX}{page.page}:{character.slug}"
        if not _fits(data):
            logger.warning("Character slug too long for a Telegram button: %s", character.slug)
            continue
        mark = "✓ " if character.slug in selected else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{character.name}", callback_data=data)])

    navigation = _page_navigation(
        GROUP_PAGE_PREFIX, language,
        previous_page=page.page - 1 if page.page > 0 else None,
        next_page=page.page + 1 if page.page + 1 < page.total_pages else None,
        page=page.page, total=page.total_pages,
        previous_key="page_previous", next_key="page_next",
    )
    if navigation:
        rows.append(navigation)

    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_create_group", n=len(selected)), callback_data=GROUP_DONE
            ),
            InlineKeyboardButton(text=t(language, "btn_cancel"), callback_data=GROUP_CANCEL),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_keyboard(
    conversation_id: uuid.UUID, page: HistoryPage, language: str | None
) -> InlineKeyboardMarkup | None:
    """Page 0 is the newest messages, so "older" means a higher page."""
    prefix = f"{HISTORY_PAGE_PREFIX}{conversation_id}:"
    navigation = _page_navigation(
        prefix, language,
        previous_page=page.page + 1 if page.page + 1 < page.total_pages else None,
        next_page=page.page - 1 if page.page > 0 else None,
        page=page.page, total=page.total_pages,
        previous_key="btn_older", next_key="btn_newer",
    )
    return InlineKeyboardMarkup(inline_keyboard=[navigation]) if navigation else None
