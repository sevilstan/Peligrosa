"""Showing a character as a slide: a picture with a caption, or text only.

Telegram cannot turn a text message into a photo message (or back) by
editing, so changing between the two sends the new slide first and then
deletes the old one.
"""

import html
import logging
from dataclasses import dataclass

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto, Message

from app.services.character_gallery_service import GalleryCharacter
from app.telegram.avatars import AvatarProvider, AvatarSource

logger = logging.getLogger(__name__)

# A photo caption is limited to 1024 characters.
_DESCRIPTION_LIMIT = 700


@dataclass(frozen=True)
class Slide:
    caption: str
    markup: InlineKeyboardMarkup
    avatar: AvatarSource | None


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_slide(
    character: GalleryCharacter,
    markup: InlineKeyboardMarkup,
    avatars: AvatarProvider,
) -> Slide:
    name = html.escape(character.name)
    description = html.escape(shorten(character.description, _DESCRIPTION_LIMIT))
    caption = f"<b>{name}</b>\n\n{description}" if description else f"<b>{name}</b>"
    return Slide(caption, markup, avatars.resolve(character.slug, character.avatar_url))


async def send_slide(message: Message, slide: Slide, avatars: AvatarProvider) -> None:
    if slide.avatar is not None:
        try:
            sent = await message.answer_photo(
                photo=slide.avatar.media,
                caption=slide.caption,
                reply_markup=slide.markup,
            )
            avatars.remember(slide.avatar, sent)
            return
        except TelegramBadRequest as exc:
            # A bad picture must never hide the character.
            logger.warning("Avatar could not be sent (%s); showing a text card.", type(exc).__name__)
            avatars.forget(slide.avatar)

    await message.answer(slide.caption, reply_markup=slide.markup)


async def edit_slide(callback: CallbackQuery, slide: Slide, avatars: AvatarProvider) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return  # inaccessible (old) message: nothing we can edit

    shows_photo = bool(message.photo)

    if slide.avatar is not None and shows_photo:
        try:
            edited = await message.edit_media(
                media=InputMediaPhoto(media=slide.avatar.media, caption=slide.caption),
                reply_markup=slide.markup,
            )
            if isinstance(edited, Message):
                avatars.remember(slide.avatar, edited)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return
            logger.warning("Avatar could not be shown (%s); showing a text card.", type(exc).__name__)
            avatars.forget(slide.avatar)
    elif slide.avatar is None and not shows_photo:
        try:
            await message.edit_text(slide.caption, reply_markup=slide.markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
        return

    # Photo <-> text switch (or a failed picture): send the new one first.
    await send_slide(message, slide, avatars)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass  # too old to delete; the new slide is already there
