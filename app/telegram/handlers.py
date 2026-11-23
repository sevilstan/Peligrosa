import html
import logging
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.character_gallery_service import CharacterGalleryService
from app.services.chat_session_service import (
    ChatContext,
    ChatNotAvailableError,
    ChatSessionService,
)
from app.services.conversation_service import AIResponseError, ConversationService
from app.telegram.avatars import AvatarProvider
from app.telegram.chat_utils import split_text, typing_indicator
from app.telegram.keyboards import (
    CHAT_PREFIX,
    GALLERY_PREFIX,
    NEW_PREFIX,
    NOOP,
    OPEN_PREFIX,
    chats_keyboard,
    main_menu,
    new_chat_keyboard,
    slider_keyboard,
)
from app.telegram.slides import build_slide, edit_slide, send_slide, shorten
from app.telegram.texts import all_labels, t

logger = logging.getLogger(__name__)

_RECAP_LIMIT = 300
_MAX_USER_TEXT = 4000


def _page_number(raw: str) -> int:
    return int(raw) if raw.isdecimal() and len(raw) < 6 else 0


# ------------------------------------------------------------- gallery


async def _slide_for_page(session: AsyncSession, avatars: AvatarProvider, language: str, page: int):
    gallery = await CharacterGalleryService(session).get_page(page)
    if not gallery.characters:
        return None
    markup = slider_keyboard(gallery, language)
    return build_slide(gallery.characters[0], markup, avatars)


async def _show_gallery(message: Message, session: AsyncSession, avatars: AvatarProvider, language: str) -> None:
    slide = await _slide_for_page(session, avatars, language, 0)
    if slide is None:
        await message.answer(t(language, "gallery_empty"))
        return
    await send_slide(message, slide, avatars)


async def start(message: Message, session: AsyncSession, user: User, avatars: AvatarProvider) -> None:
    language = user.language_code
    name = f", {html.escape(user.display_name)}" if user.display_name else ""
    await message.answer(t(language, "welcome", name=name), reply_markup=main_menu(language))
    await _show_gallery(message, session, avatars, language)


async def characters(message: Message, session: AsyncSession, user: User, avatars: AvatarProvider) -> None:
    await _show_gallery(message, session, avatars, user.language_code)


async def gallery_page(callback: CallbackQuery, session: AsyncSession, user: User, avatars: AvatarProvider) -> None:
    page = _page_number(callback.data.removeprefix(GALLERY_PREFIX))
    slide = await _slide_for_page(session, avatars, user.language_code, page)
    if slide is not None:
        await edit_slide(callback, slide, avatars)
    await callback.answer()


async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


# ---------------------------------------------------------- chat start


async def _announce_chat(
    message: Message,
    service: ChatSessionService,
    user: User,
    context: ChatContext,
) -> None:
    """Tell the user which chat is active and where they left off."""
    language = user.language_code
    name = html.escape(context.character.name)

    key = "chat_new" if context.created else "chat_resumed"
    text = t(language, key, name=name)

    if not context.created:
        last = await service.last_character_message(user.id, context.conversation_id)
        if last:
            text += "\n\n" + t(
                language,
                "chat_recap",
                name=name,
                text=html.escape(shorten(last, _RECAP_LIMIT)),
            )

    await message.answer(
        text,
        reply_markup=new_chat_keyboard(context.character, language),
    )


async def open_chat(
    callback: CallbackQuery, session: AsyncSession, user: User, provider, avatars: AvatarProvider
) -> None:
    language = user.language_code
    slug = callback.data.removeprefix(OPEN_PREFIX)
    service = ChatSessionService(session, provider)

    try:
        context = await service.open_character_chat(user.id, slug)
    except ChatNotAvailableError:
        await callback.answer(t(language, "character_missing"), show_alert=True)
        return

    await callback.answer()
    if isinstance(callback.message, Message):
        await _announce_chat(callback.message, service, user, context)


async def new_chat(callback: CallbackQuery, session: AsyncSession, user: User, provider) -> None:
    language = user.language_code
    service = ChatSessionService(session, provider)

    try:
        context = await service.start_new_chat(user.id, callback.data.removeprefix(NEW_PREFIX))
    except ChatNotAvailableError:
        await callback.answer(t(language, "character_missing"), show_alert=True)
        return

    await callback.answer()
    if isinstance(callback.message, Message):
        await _announce_chat(callback.message, service, user, context)


async def new_chat_command(message: Message, session: AsyncSession, user: User, provider) -> None:
    service = ChatSessionService(session, provider)
    active = await service.get_active(user.id)

    if active is None:
        await message.answer(t(user.language_code, "no_active_chat"))
        return

    context = await service.start_new_chat(user.id, active.character.slug)
    await _announce_chat(message, service, user, context)


# ------------------------------------------------------------ chat list


async def _chats_view(message: Message, session: AsyncSession, user: User, provider) -> None:
    language = user.language_code
    chats = await ChatSessionService(session, provider).list_chats(user.id)

    if not chats:
        await message.answer(t(language, "chats_empty"))
        return

    await message.answer(t(language, "chats_title"), reply_markup=chats_keyboard(chats))


async def chats_command(message: Message, session: AsyncSession, user: User, provider) -> None:
    await _chats_view(message, session, user, provider)


async def switch_chat(callback: CallbackQuery, session: AsyncSession, user: User, provider) -> None:
    language = user.language_code
    service = ChatSessionService(session, provider)

    try:
        conversation_id = uuid.UUID(callback.data.removeprefix(CHAT_PREFIX))
        context = await service.switch_to(user.id, conversation_id)
    except (ValueError, ChatNotAvailableError):
        await callback.answer(t(language, "chat_unavailable"), show_alert=True)
        return

    await callback.answer()
    if isinstance(callback.message, Message):
        await _announce_chat(callback.message, service, user, context)


# ------------------------------------------------------------- messaging


async def chat_text(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    provider,
) -> None:
    language = user.language_code
    text = message.text.strip()[:_MAX_USER_TEXT]
    if not text:
        return

    # Ordering per user is guaranteed by ChatOrderMiddleware.
    active = await ChatSessionService(session, provider).get_active(user.id)

    if active is None:
        await message.answer(t(language, "no_active_chat"), reply_markup=main_menu(language))
        return

    try:
        async with typing_indicator(bot, message.chat.id):
            reply = await ConversationService(session, ai_provider=provider).send_message(
                conversation_id=active.conversation_id,
                user_id=user.id,
                content=text,
            )
    except AIResponseError:
        await message.answer(t(language, "ai_error"))
        return
    except ValueError:
        logger.warning("Chat message could not be sent: conversation unavailable.")
        await message.answer(t(language, "chat_unavailable"))
        return

    # Character replies are plain text: never interpreted as HTML.
    for part in split_text(reply.content):
        await message.answer(part, parse_mode=None)


async def unknown_command(message: Message, user: User) -> None:
    await message.answer(t(user.language_code, "unknown_command"), reply_markup=main_menu(user.language_code))


async def non_text(message: Message, user: User) -> None:
    await message.answer(t(user.language_code, "text_only"))


def build_router() -> Router:
    """A fresh router per dispatcher (a router can only be attached once)."""
    router = Router(name="main")

    router.message.register(start, Command("start"))
    router.message.register(characters, Command("characters"))
    router.message.register(characters, F.text.in_(all_labels("menu_characters")))
    router.message.register(chats_command, Command("chats"))
    router.message.register(chats_command, F.text.in_(all_labels("menu_chats")))
    router.message.register(new_chat_command, Command("new"))
    router.message.register(unknown_command, F.text.startswith("/"))
    router.message.register(chat_text, F.text)
    router.message.register(non_text)

    router.callback_query.register(gallery_page, F.data.startswith(GALLERY_PREFIX))
    router.callback_query.register(open_chat, F.data.startswith(OPEN_PREFIX))
    router.callback_query.register(new_chat, F.data.startswith(NEW_PREFIX))
    router.callback_query.register(switch_chat, F.data.startswith(CHAT_PREFIX))
    router.callback_query.register(noop, F.data == NOOP)

    return router
