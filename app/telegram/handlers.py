import html
import logging
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.character_gallery_service import CharacterGalleryService
from app.services.character_removal_service import (
    CharacterNotFoundError,
    CharacterRemovalService,
    RemovalSummary,
)
from app.services.chat_session_service import (
    GROUP_MAX_CHARACTERS,
    GROUP_MIN_CHARACTERS,
    ChatContext,
    HistoryPage,
    InvalidGroupError,
    ChatNotAvailableError,
    ChatSessionService,
)
from app.services.conversation_service import AIResponseError, ConversationService
from app.telegram.avatars import AvatarProvider
from app.telegram.chat_utils import edit_text_in_place, split_text, typing_indicator
from app.telegram.keyboards import (
    CHAT_PREFIX,
    CHATS_PAGE_PREFIX,
    DELETE_CANCEL,
    DELETE_CONFIRM_PREFIX,
    DELETE_PREFIX,
    GALLERY_PREFIX,
    GROUP_CANCEL,
    GROUP_DONE,
    GROUP_NEW,
    GROUP_PAGE_PREFIX,
    GROUP_SELECT_PREFIX,
    HISTORY_OPEN_PREFIX,
    HISTORY_PAGE_PREFIX,
    NEW_PREFIX,
    NOOP,
    OPEN_PREFIX,
    chat_actions_keyboard,
    chats_keyboard,
    delete_confirm_keyboard,
    group_picker_keyboard,
    history_keyboard,
    main_menu,
    new_group_keyboard,
    slider_keyboard,
)
from app.telegram.group_drafts import GroupDrafts
from app.telegram.slides import build_slide, edit_slide, send_slide, shorten
from app.telegram.texts import all_labels, t

logger = logging.getLogger(__name__)

PICKER_PAGE_SIZE = 6
_RECAP_LIMIT = 300
_HISTORY_MESSAGE_LIMIT = 350
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
    name = html.escape(context.name)

    if context.is_group:
        key = "group_ready" if context.created else "group_resumed"
        text = t(language, key, name=name, soon=t(language, "group_soon"))
    else:
        key = "chat_new" if context.created else "chat_resumed"
        text = t(language, key, name=name)

    if not context.created and not context.is_group:
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
        reply_markup=chat_actions_keyboard(
            context.character, context.conversation_id, language, is_group=context.is_group
        ),
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

    if active.is_group:
        await message.answer(t(user.language_code, "new_chat_in_group"))
        return

    context = await service.start_new_chat(user.id, active.character.slug)
    await _announce_chat(message, service, user, context)


# ------------------------------------------------------------ chat list


async def _chats_page(session: AsyncSession, user: User, provider, page: int):
    language = user.language_code
    listing = await ChatSessionService(session, provider).list_chats(user.id, page)

    if not listing.items:
        return t(language, "chats_empty"), new_group_keyboard(language)

    text = t(language, "chats_title", page=listing.page + 1, total=listing.total_pages)
    return text, chats_keyboard(listing, language)


async def chats_command(message: Message, session: AsyncSession, user: User, provider) -> None:
    text, markup = await _chats_page(session, user, provider, 0)
    await message.answer(text, reply_markup=markup)


async def chats_page(callback: CallbackQuery, session: AsyncSession, user: User, provider) -> None:
    page = _page_number(callback.data.removeprefix(CHATS_PAGE_PREFIX))
    text, markup = await _chats_page(session, user, provider, page)
    await edit_text_in_place(callback, text, markup)
    await callback.answer()


# -------------------------------------------------------------- history


def _history_text(language: str, page: HistoryPage) -> str:
    name = html.escape(page.name)
    parts = [t(language, "history_title", name=name, page=page.page + 1, total=page.total_pages)]

    if not page.messages:
        parts.append(t(language, "history_empty"))

    for item in page.messages:
        who = t(language, "history_you") if item.from_user else name
        body = html.escape(shorten(item.content, _HISTORY_MESSAGE_LIMIT))
        parts.append(f"<b>{who}:</b> {body}")

    return "\n\n".join(parts)


async def _history_view(session: AsyncSession, user: User, provider, conversation_id, page: int):
    language = user.language_code
    history = await ChatSessionService(session, provider).get_history(user.id, conversation_id, page)
    return _history_text(language, history), history_keyboard(conversation_id, history, language)


async def history_open(callback: CallbackQuery, session: AsyncSession, user: User, provider) -> None:
    """The History button under a chat message: newest messages, as a new message."""
    language = user.language_code
    try:
        conversation_id = uuid.UUID(callback.data.removeprefix(HISTORY_OPEN_PREFIX))
        text, markup = await _history_view(session, user, provider, conversation_id, 0)
    except (ValueError, ChatNotAvailableError):
        await callback.answer(t(language, "chat_unavailable"), show_alert=True)
        return

    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(text, reply_markup=markup)


async def history_page(callback: CallbackQuery, session: AsyncSession, user: User, provider) -> None:
    language = user.language_code
    try:
        raw_id, _, raw_page = callback.data.removeprefix(HISTORY_PAGE_PREFIX).partition(":")
        text, markup = await _history_view(
            session, user, provider, uuid.UUID(raw_id), _page_number(raw_page)
        )
    except (ValueError, ChatNotAvailableError):
        await callback.answer(t(language, "chat_unavailable"), show_alert=True)
        return

    await edit_text_in_place(callback, text, markup)
    await callback.answer()


async def history_command(message: Message, session: AsyncSession, user: User, provider) -> None:
    """History of the active chat (command and bottom-menu button)."""
    language = user.language_code
    active = await ChatSessionService(session, provider).get_active(user.id)

    if active is None:
        await message.answer(t(language, "no_active_chat"))
        return

    text, markup = await _history_view(session, user, provider, active.conversation_id, 0)
    await message.answer(text, reply_markup=markup)


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


# -------------------------------------------------------------- deleting


def _removal_numbers(summary: RemovalSummary) -> dict:
    return {
        "name": html.escape(summary.character.name),
        "chats": summary.direct_chats,
        "memories": summary.memories,
        "groups": summary.groups,
        "groups_deleted": summary.groups_deleted,
    }


async def _ask_to_delete(message: Message, session: AsyncSession, user: User, slug: str) -> str | None:
    """Show what would be deleted and ask. Returns an alert text if not possible."""
    language = user.language_code

    try:
        summary = await CharacterRemovalService(session).preview(user.id, slug)
    except CharacterNotFoundError:
        return t(language, "character_missing")

    name = html.escape(summary.character.name)
    markup = delete_confirm_keyboard(slug, language)
    if summary.is_empty or markup is None:
        return t(language, "delete_nothing", name=name)

    await message.answer(
        t(language, "delete_confirm", **_removal_numbers(summary)), reply_markup=markup
    )
    return None


async def delete_ask(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    slug = callback.data.removeprefix(DELETE_PREFIX)
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    problem = await _ask_to_delete(callback.message, session, user, slug)
    await callback.answer(problem, show_alert=bool(problem))


async def delete_command(message: Message, session: AsyncSession, user: User, provider) -> None:
    """/delete: the character of the active direct chat."""
    language = user.language_code
    active = await ChatSessionService(session, provider).get_active(user.id)

    if active is None or active.is_group:
        await message.answer(t(language, "delete_pick"))
        return

    problem = await _ask_to_delete(message, session, user, active.character.slug)
    if problem:
        await message.answer(problem)


async def delete_confirm(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    language = user.language_code
    slug = callback.data.removeprefix(DELETE_CONFIRM_PREFIX)

    try:
        summary = await CharacterRemovalService(session).remove(user.id, slug)
    except CharacterNotFoundError:
        await callback.answer(t(language, "character_missing"), show_alert=True)
        return

    logger.info(
        "User deleted a character: chats=%d memories=%d groups=%d",
        summary.direct_chats, summary.memories, summary.groups,
    )
    await edit_text_in_place(
        callback, t(language, "delete_done", **_removal_numbers(summary)), None
    )
    await callback.answer()


async def delete_cancel(callback: CallbackQuery, user: User) -> None:
    await edit_text_in_place(callback, t(user.language_code, "delete_cancelled"), None)
    await callback.answer()


# --------------------------------------------------------------- groups


async def _picker(session: AsyncSession, drafts: GroupDrafts, user: User, page: int):
    language = user.language_code
    gallery = await CharacterGalleryService(session, page_size=PICKER_PAGE_SIZE).get_page(page)

    if not gallery.characters:
        return t(language, "gallery_empty"), None

    selected = drafts.get(user.id) or []
    text = t(
        language,
        "group_pick",
        min=GROUP_MIN_CHARACTERS,
        max=GROUP_MAX_CHARACTERS,
        selected=len(selected),
    )
    return text, group_picker_keyboard(gallery, selected, language)


async def _start_group(message: Message, session: AsyncSession, user: User, drafts: GroupDrafts) -> None:
    drafts.start(user.id)
    text, markup = await _picker(session, drafts, user, 0)
    await message.answer(text, reply_markup=markup)


async def group_command(message: Message, session: AsyncSession, user: User, drafts: GroupDrafts) -> None:
    await _start_group(message, session, user, drafts)


async def group_new(callback: CallbackQuery, session: AsyncSession, user: User, drafts: GroupDrafts) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _start_group(callback.message, session, user, drafts)


async def group_select(callback: CallbackQuery, session: AsyncSession, user: User, drafts: GroupDrafts) -> None:
    language = user.language_code
    raw_page, _, slug = callback.data.removeprefix(GROUP_SELECT_PREFIX).partition(":")

    if drafts.get(user.id) is None:
        await callback.answer(t(language, "group_expired"), show_alert=True)
        return

    # The slug comes from the client: look it up, never trust it.
    if await CharacterGalleryService(session).get_character(slug) is None:
        await callback.answer(t(language, "group_unavailable"), show_alert=True)
        return

    if not drafts.toggle(user.id, slug, GROUP_MAX_CHARACTERS):
        await callback.answer(t(language, "group_max", max=GROUP_MAX_CHARACTERS), show_alert=True)
        return

    text, markup = await _picker(session, drafts, user, _page_number(raw_page))
    await edit_text_in_place(callback, text, markup)
    await callback.answer()


async def group_page(callback: CallbackQuery, session: AsyncSession, user: User, drafts: GroupDrafts) -> None:
    if drafts.get(user.id) is None:
        await callback.answer(t(user.language_code, "group_expired"), show_alert=True)
        return

    page = _page_number(callback.data.removeprefix(GROUP_PAGE_PREFIX))
    text, markup = await _picker(session, drafts, user, page)
    await edit_text_in_place(callback, text, markup)
    await callback.answer()


async def group_cancel(callback: CallbackQuery, user: User, drafts: GroupDrafts) -> None:
    drafts.clear(user.id)
    await edit_text_in_place(callback, t(user.language_code, "group_cancelled"), None)
    await callback.answer()


async def group_done(
    callback: CallbackQuery, session: AsyncSession, user: User, provider, drafts: GroupDrafts
) -> None:
    language = user.language_code
    selected = drafts.get(user.id)

    if selected is None:
        await callback.answer(t(language, "group_expired"), show_alert=True)
        return

    service = ChatSessionService(session, provider)
    try:
        context = await service.create_group(user.id, selected)
    except InvalidGroupError as exc:
        key, values = {
            "too_few": ("group_min", {"min": GROUP_MIN_CHARACTERS}),
            "too_many": ("group_max", {"max": GROUP_MAX_CHARACTERS}),
        }.get(exc.reason, ("group_unavailable", {}))
        await callback.answer(t(language, key, **values), show_alert=True)
        return

    drafts.clear(user.id)
    await edit_text_in_place(
        callback, t(language, "group_created", name=html.escape(context.name)), None
    )
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

    if active.is_group:
        # Nobody answers in groups yet: say so instead of saving a message
        # that would get no reply.
        await message.answer(t(language, "group_soon"))
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
    router.message.register(history_command, Command("history"))
    router.message.register(history_command, F.text.in_(all_labels("menu_history")))
    router.message.register(new_chat_command, Command("new"))
    router.message.register(group_command, Command("newgroup"))
    router.message.register(delete_command, Command("delete"))
    router.message.register(unknown_command, F.text.startswith("/"))
    router.message.register(chat_text, F.text)
    router.message.register(non_text)

    router.callback_query.register(gallery_page, F.data.startswith(GALLERY_PREFIX))
    router.callback_query.register(open_chat, F.data.startswith(OPEN_PREFIX))
    router.callback_query.register(new_chat, F.data.startswith(NEW_PREFIX))
    router.callback_query.register(switch_chat, F.data.startswith(CHAT_PREFIX))
    router.callback_query.register(chats_page, F.data.startswith(CHATS_PAGE_PREFIX))
    router.callback_query.register(history_open, F.data.startswith(HISTORY_OPEN_PREFIX))
    router.callback_query.register(history_page, F.data.startswith(HISTORY_PAGE_PREFIX))
    router.callback_query.register(delete_ask, F.data.startswith(DELETE_PREFIX))
    router.callback_query.register(delete_confirm, F.data.startswith(DELETE_CONFIRM_PREFIX))
    router.callback_query.register(delete_cancel, F.data == DELETE_CANCEL)
    router.callback_query.register(group_new, F.data == GROUP_NEW)
    router.callback_query.register(group_select, F.data.startswith(GROUP_SELECT_PREFIX))
    router.callback_query.register(group_page, F.data.startswith(GROUP_PAGE_PREFIX))
    router.callback_query.register(group_done, F.data == GROUP_DONE)
    router.callback_query.register(group_cancel, F.data == GROUP_CANCEL)
    router.callback_query.register(noop, F.data == NOOP)

    return router
