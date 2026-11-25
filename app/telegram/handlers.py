import html
import logging
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.services.user_data_service import UserDataService
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
from app.services.credit_service import (
    CreditConfig,
    CreditService,
    DailyCapReached,
    InsufficientCredits,
)
from app.services.payment_service import CURRENCY, PaymentService, build_catalog, payload_for
from app.services.group_conversation_service import FOLLOWUP_CHANCE, GroupConversationService
from app.services.conversation_service import AIResponseError, ConversationService
from app.telegram.avatars import AvatarProvider
from app.telegram.chat_utils import (
    TELEGRAM_MESSAGE_LIMIT,
    edit_text_in_place,
    split_text,
    typing_indicator,
)
from app.telegram.keyboards import (
    WIPE_CANCEL,
    WIPE_CONFIRM,
    wipe_keyboard,
    BUY_ITEM_PREFIX,
    BUY_OPEN,
    buy_keyboard,
    buy_prompt_keyboard,
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
    else:
        key = "chat_new" if context.created else "chat_resumed"

    # A visible divider: the chat list above belongs to the previous chat.
    text = (
        t(language, "chat_divider", name=name, icon="👥" if context.is_group else "💬")
        + "\n"
        + t(language, key, name=name)
    )

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


# ------------------------------------------------------------- proactive

_PROACTIVE_ON = {"on", "aç", "ac", "açık", "acik"}
_PROACTIVE_OFF = {"off", "kapat", "kapalı", "kapali"}


async def proactive_command(
    message: Message, command: CommandObject, session: AsyncSession, user: User
) -> None:
    """/proactive [on|off]: let characters message first (opt-in)."""
    language = user.language_code

    if not settings.INITIATIVE_ENABLED:
        await message.answer(t(language, "proactive_unavailable"))
        return

    choice = (command.args or "").strip().lower()

    if choice in _PROACTIVE_ON or choice in _PROACTIVE_OFF:
        user.proactive_enabled = choice in _PROACTIVE_ON
        await session.commit()
        await message.answer(t(language, "proactive_on" if user.proactive_enabled else "proactive_off"))
        return

    await message.answer(
        t(language, "proactive_status_on" if user.proactive_enabled else "proactive_status_off")
    )


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
        who = t(language, "history_you") if item.from_user else html.escape(item.speaker or page.name)
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
    receipt = await _charge_or_explain(
        callback,
        session,
        user,
        CreditConfig.from_settings(settings).group_create_cost,
        "group_create",
        included_in_subscription=settings.SUB_GROUP_CREATE_FREE,
    )
    if receipt is None:
        return

    try:
        context = await service.create_group(user.id, selected)
    except InvalidGroupError as exc:
        await _credits(session).refund(receipt)
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


# --------------------------------------------------------------- credits


def _credits(session: AsyncSession) -> CreditService:
    return CreditService(session, CreditConfig.from_settings(settings))


def _admin_ids() -> set[int]:
    ids = set()
    for part in settings.ADMIN_TELEGRAM_IDS.split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return ids


async def credits_command(message: Message, session: AsyncSession, user: User) -> None:
    language = user.language_code
    config = CreditConfig.from_settings(settings)

    if not config.enabled:
        await message.answer(t(language, "credits_off"))
        return

    service = _credits(session)
    await service.ensure_trial(user.id)
    status = await service.status(user.id)

    key = "credits_subscribed" if status.subscribed else "credits_balance"
    await message.answer(
        t(
            language,
            key,
            credits=status.credits,
            until=status.subscription_until.strftime("%Y-%m-%d") if status.subscription_until else "-",
            message=config.message_cost,
            group_message=config.group_message_cost,
            group_create=config.group_create_cost,
            cap=config.subscriber_daily_cap,
        ),
        reply_markup=buy_prompt_keyboard(language) if _catalog() else None,
    )


async def grant_command(
    message: Message, command: CommandObject, session: AsyncSession, user: User
) -> None:
    """Operator only: /grant <telegram_id> <amount>. Anyone else just gets the
    "unknown command" answer, so the command's existence is not revealed."""
    if user.telegram_id not in _admin_ids():
        await unknown_command(message, user)
        return

    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[0].lstrip("-").isdigit() or not parts[1].isdigit() or int(parts[1]) < 1:
        await message.answer("Usage: /grant <telegram_id> <credits>")
        return

    target = (
        await session.execute(select(User).where(User.telegram_id == int(parts[0])))
    ).scalar_one_or_none()
    if target is None:
        await message.answer("No user with that Telegram id.")
        return

    balance = await CreditService(session, CreditConfig(enabled=True)).grant(target.id, int(parts[1]))
    await message.answer(f"Granted {int(parts[1])}. New balance: {balance}.")


async def _charge_or_explain(
    message_or_callback, session, user, cost, reason, conversation_id=None, included_in_subscription=True
):
    """Charge, or tell the user why not. Returns the receipt, or None."""
    language = user.language_code
    config = CreditConfig.from_settings(settings)
    is_callback = isinstance(message_or_callback, CallbackQuery)

    try:
        return await CreditService(session, config).charge(
            user.id,
            cost,
            reason,
            conversation_id=conversation_id,
            included_in_subscription=included_in_subscription,
        )
    except InsufficientCredits as exc:
        key = "group_needs_credits" if reason == "group_create" else "credits_empty"
        text = t(language, key, cost=exc.needed, credits=exc.available)
    except DailyCapReached:
        text = t(language, "daily_cap")

    if is_callback:
        await message_or_callback.answer(text, show_alert=True)
    else:
        await message_or_callback.answer(
            text,
            reply_markup=buy_prompt_keyboard(language) if _catalog() else None,
        )
    return None


# ------------------------------------------------------------------ shop


def _catalog():
    return build_catalog(settings) if settings.CREDITS_ENABLED else []


async def _show_shop(message: Message, user: User) -> None:
    language = user.language_code
    catalog = _catalog()
    if not catalog:
        await message.answer(t(language, "buy_unavailable"))
        return
    await message.answer(t(language, "buy_menu"), reply_markup=buy_keyboard(catalog, language))


async def buy_command(message: Message, user: User) -> None:
    await _show_shop(message, user)


async def buy_open(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _show_shop(callback.message, user)


async def buy_item(callback: CallbackQuery, user: User) -> None:
    language = user.language_code
    key = callback.data.removeprefix(BUY_ITEM_PREFIX)
    product = next((p for p in _catalog() if p.key == key), None)

    if product is None or not isinstance(callback.message, Message):
        await callback.answer(t(language, "buy_unavailable"), show_alert=True)
        return

    await callback.answer()
    if product.is_subscription:
        values = {"days": product.days, "cap": max(1, settings.SUB_DAILY_MESSAGE_CAP)}
        title = t(language, "invoice_sub_title", **values)
        description = t(
            language,
            "invoice_sub_description_groups" if settings.SUB_GROUP_CREATE_FREE else "invoice_sub_description",
            **values,
        )
    else:
        title = t(language, "invoice_pack_title", credits=product.credits)
        description = t(language, "invoice_pack_description")

    await callback.message.answer_invoice(
        title=title,
        description=description,
        payload=payload_for(product),
        currency=CURRENCY,
        prices=[LabeledPrice(label=title, amount=product.stars)],
        provider_token="",
    )


def _payments(session: AsyncSession) -> PaymentService:
    return PaymentService(session, _catalog(), CreditConfig.from_settings(settings))


async def pre_checkout(query: PreCheckoutQuery, session: AsyncSession, user: User) -> None:
    """Telegram waits only 10 seconds: nothing here but a quick check."""
    product = _payments(session).check_order(
        query.invoice_payload, query.currency, query.total_amount
    )
    if product is None:
        await query.answer(ok=False, error_message=t(user.language_code, "precheckout_rejected"))
        return
    await query.answer(ok=True)


async def successful_payment(message: Message, session: AsyncSession, user: User) -> None:
    language = user.language_code
    payment = message.successful_payment
    charge_id = payment.telegram_payment_charge_id

    try:
        delivery = await _payments(session).deliver(
            user.id, payment.invoice_payload, payment.total_amount, charge_id
        )
    except Exception as exc:
        # Money was taken: never lose track of it. The charge id is not a secret.
        logger.error("Could not deliver payment %s: %s", charge_id, type(exc).__name__)
        await message.answer(t(language, "pay_problem"))
        return

    if delivery.duplicate:
        return
    if delivery.product is None:
        await message.answer(t(language, "pay_problem"))
        return

    if delivery.product.is_subscription:
        await message.answer(
            t(
                language,
                "pay_thanks_sub",
                until=delivery.subscription_until.strftime("%Y-%m-%d"),
            )
        )
    else:
        await message.answer(t(language, "pay_thanks_pack", credits=delivery.credits))


async def terms_command(message: Message, user: User) -> None:
    await message.answer(t(user.language_code, "terms_text"))


async def support_command(message: Message, user: User) -> None:
    key = "support_text" if message.text.lstrip("/").startswith("support") else "paysupport_text"
    if not settings.SUPPORT_CONTACT:
        await message.answer(t(user.language_code, "support_missing"))
        return
    await message.answer(t(user.language_code, key, contact=html.escape(settings.SUPPORT_CONTACT)))


async def refund_command(
    message: Message, command: CommandObject, bot: Bot, session: AsyncSession, user: User
) -> None:
    """Operator only: /refund <telegram_charge_id>. Telegram returns the Stars
    first; only when that works do we take back what the payment gave."""
    if user.telegram_id not in _admin_ids():
        await unknown_command(message, user)
        return

    charge_id = (command.args or "").strip()
    service = _payments(session)
    found = await service.find(charge_id) if charge_id else None

    if found is None:
        await message.answer("Usage: /refund <telegram_charge_id> (unknown payment).")
        return

    payment, buyer_telegram_id = found
    if payment.status == "refunded" or buyer_telegram_id is None:
        await message.answer("Already refunded.")
        return

    try:
        await bot.refund_star_payment(
            user_id=buyer_telegram_id, telegram_payment_charge_id=charge_id
        )
    except TelegramAPIError as exc:
        logger.warning("Telegram refused a refund: %s", type(exc).__name__)
        await message.answer("Telegram refused the refund. Nothing was changed.")
        return

    await service.reverse(charge_id)
    await message.answer("Refunded and taken back.")


# ------------------------------------------------------------- messaging


async def _send_as(message: Message, name: str, content: str) -> None:
    """One bot, several voices: the name opens the message, in every chat, so
    it is clear who speaks even when chats were switched above. Only the name
    is HTML (escaped); the character's words stay plain text."""
    # Telegram counts the visible characters, so the header ("Name: ") takes
    # room from the first part.
    parts = split_text(content, TELEGRAM_MESSAGE_LIMIT - len(name) - 2)
    header = f"<b>{html.escape(name, quote=False)}:</b> "
    # Quotes need no escaping in text; only <, > and & matter.
    await message.answer(header + html.escape(parts[0], quote=False), parse_mode="HTML")
    for part in parts[1:]:
        await message.answer(part, parse_mode=None)


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

    config = CreditConfig.from_settings(settings)
    receipt = await _charge_or_explain(
        message,
        session,
        user,
        config.group_message_cost if active.is_group else config.message_cost,
        "group_message" if active.is_group else "message",
        active.conversation_id,
    )
    if receipt is None:
        return

    if active.is_group:
        await _group_text(
            message, bot, session, user, provider, active.conversation_id, text, receipt
        )
        return

    try:
        async with typing_indicator(bot, message.chat.id):
            reply = await ConversationService(session, ai_provider=provider).send_message(
                conversation_id=active.conversation_id,
                user_id=user.id,
                content=text,
            )
    except AIResponseError:
        await _credits(session).refund(receipt)
        await message.answer(t(language, "ai_error"))
        return
    except ValueError:
        await _credits(session).refund(receipt)
        logger.warning("Chat message could not be sent: conversation unavailable.")
        await message.answer(t(language, "chat_unavailable"))
        return

    await _send_as(message, active.name, reply.content)


async def _group_text(
    message, bot, session, user, provider, conversation_id, text, receipt=None
) -> None:
    language = user.language_code

    async def deliver(reply) -> None:
        await _send_as(message, reply.speaker.name, reply.content)

    try:
        # Each reply is sent as soon as it exists; typing stays on meanwhile.
        async with typing_indicator(bot, message.chat.id):
            await GroupConversationService(
                session, ai_provider=provider, followup_chance=FOLLOWUP_CHANCE, reflection=True
            ).send_message(
                conversation_id=conversation_id,
                user_id=user.id,
                content=text,
                on_reply=deliver,
            )
    except AIResponseError:
        if receipt is not None:
            await _credits(session).refund(receipt)
        await message.answer(t(language, "ai_error"))
    except ValueError:
        if receipt is not None:
            await _credits(session).refund(receipt)
        logger.warning("Group message could not be sent: group unavailable.")
        await message.answer(t(language, "chat_unavailable"))


async def deletedata_command(message: Message, user: User) -> None:
    await message.answer(
        t(user.language_code, "wipe_warning"), reply_markup=wipe_keyboard(user.language_code)
    )


async def wipe_confirm(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    language = user.language_code
    await callback.answer()
    try:
        result = await UserDataService(session).delete_all(user.id)
    except Exception as exc:
        logger.error("Could not delete a user's data: %s", type(exc).__name__)
        text = t(language, "wipe_failed")
    else:
        # The internal id (no name) is logged so deletions can be re-applied after
        # restoring an old backup (scripts/reapply_deletions.py).
        logger.info("User data deleted: user_id=%s chats=%d", user.id, result.conversations)
        text = t(
            language, "wipe_done", conversations=result.conversations, memories=result.memories
        )
    await edit_text_in_place(callback, text, None)


async def wipe_cancel(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    await edit_text_in_place(callback, t(user.language_code, "wipe_cancelled"), None)


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
    router.message.register(proactive_command, Command("proactive"))
    router.message.register(deletedata_command, Command("deletedata"))
    router.message.register(credits_command, Command("credits"))
    router.message.register(buy_command, Command("buy"))
    router.message.register(terms_command, Command("terms"))
    router.message.register(support_command, Command("support", "paysupport"))
    router.message.register(refund_command, Command("refund"))
    router.message.register(successful_payment, F.successful_payment)
    router.pre_checkout_query.register(pre_checkout)
    router.message.register(grant_command, Command("grant"))
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
    router.callback_query.register(buy_open, F.data == BUY_OPEN)
    router.callback_query.register(buy_item, F.data.startswith(BUY_ITEM_PREFIX))
    router.callback_query.register(wipe_confirm, F.data == WIPE_CONFIRM)
    router.callback_query.register(wipe_cancel, F.data == WIPE_CANCEL)
    router.callback_query.register(noop, F.data == NOOP)

    return router
