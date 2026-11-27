import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, ErrorEvent, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.alerts import install_alerts, parse_admin_ids, remove_alerts
from app.core.config import settings
from app.providers.xavira_provider import XaviraImageProvider
from app.services.character_definition_loader import CharacterDefinitionLoader
from app.services.image_service import ImageFeature
from app.services.image_storage import LocalImageStorage
from app.telegram.avatars import AvatarProvider
from app.telegram.photo_offers import PhotoOffers
from app.telegram.chat_utils import UserLocks
from app.telegram.group_drafts import GroupDrafts
from app.services.initiative_service import InitiativeConfig
from app.telegram.handlers import build_router
from app.telegram.initiative_runner import InitiativeRunner
from app.telegram.middlewares import ChatOrderMiddleware, DbSessionMiddleware, UserMiddleware
from app.telegram.texts import TEXTS, resolve_language, t

logger = logging.getLogger(__name__)

_COMMANDS = (
    ("start", "cmd_start"),
    ("characters", "cmd_characters"),
    ("chats", "cmd_chats"),
    ("history", "cmd_history"),
    ("new", "cmd_new"),
    ("name", "cmd_name"),
    ("newgroup", "cmd_newgroup"),
    ("delete", "cmd_delete"),
    ("proactive", "cmd_proactive"),
    ("credits", "cmd_credits"),
    ("buy", "cmd_buy"),
    ("terms", "cmd_terms"),
    ("support", "cmd_support"),
    ("paysupport", "cmd_paysupport"),
)


def build_initiative_runner(bot, session_maker, provider, locks) -> InitiativeRunner:
    return InitiativeRunner(
        bot,
        session_maker,
        provider,
        locks,
        config=InitiativeConfig.from_settings(settings),
        check_seconds=settings.INITIATIVE_CHECK_SECONDS,
        max_per_check=settings.INITIATIVE_MAX_PER_CHECK,
    )


async def sync_characters_on_start(session_maker) -> None:
    """New YAML files become characters in the database at every start.

    Best effort: a problem here must never keep the bot from starting.
    """
    from app.services.character_sync_service import CharacterSyncService

    try:
        async with session_maker() as session:
            result = await CharacterSyncService(session).sync()
    except Exception as exc:
        logger.error("Could not sync characters: %s", type(exc).__name__)
        return

    if result.created:
        logger.info("New characters available: %s", ", ".join(result.created))
    for slug in result.failed:
        logger.error("Character '%s' has an invalid definition and was skipped.", slug)


def build_inner_provider():
    """The provider chosen by AI_PROVIDER. Fails early (clear message) when its
    key is missing or the name is unknown."""
    name = settings.AI_PROVIDER.strip().lower()

    if name == "groq":
        from app.providers.groq_provider import GroqProvider

        return GroqProvider()
    if name == "roleplay":
        from app.providers.roleplay_provider import RoleplayProvider

        return RoleplayProvider()

    raise RuntimeError(f"Unknown AI_PROVIDER '{settings.AI_PROVIDER}'. Use 'groq' or 'roleplay'.")


def build_ai_provider():
    """The provider the bot talks to, kept inside its request limits."""
    from app.providers.rate_limited_provider import RateLimitedProvider
    from app.providers.usage_tracking_provider import UsageTrackingProvider

    # Outermost, so calls that fail while waiting for a slot are counted too.
    return UsageTrackingProvider(
        RateLimitedProvider(
            build_inner_provider(),
            max_per_minute=settings.AI_MAX_REQUESTS_PER_MINUTE,
            max_concurrent=settings.AI_MAX_CONCURRENT_REQUESTS,
            max_wait=settings.AI_MAX_QUEUE_WAIT_SECONDS,
        )
    )


def build_image_feature() -> ImageFeature | None:
    """Pictures in chats, or None when they are switched off. Switched on
    without a key is a mistake worth stopping for, not a silent no-op."""
    if not settings.IMAGES_ENABLED:
        return None
    if not settings.XAVIRA_API_KEY:
        raise RuntimeError("IMAGES_ENABLED=true needs XAVIRA_API_KEY.")
    return ImageFeature(
        provider=XaviraImageProvider(
            api_key=settings.XAVIRA_API_KEY,
            base_url=settings.XAVIRA_BASE_URL,
            resolution=settings.XAVIRA_RESOLUTION,
            max_wait=settings.XAVIRA_MAX_WAIT_SECONDS,
            low_balance=settings.XAVIRA_LOW_BALANCE,
        ),
        storage=LocalImageStorage(settings.IMAGE_STORAGE_DIR),
        loader=CharacterDefinitionLoader(),
        cache_min_variants=settings.IMAGE_CACHE_MIN_VARIANTS,
    )


def build_bot(token: str) -> Bot:
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher(
    session_maker: async_sessionmaker[AsyncSession],
    ai_provider=None,
    avatars: AvatarProvider | None = None,
    locks: UserLocks | None = None,
    images: ImageFeature | None = None,
    offers: PhotoOffers | None = None,
) -> Dispatcher:
    # Everything handlers need beyond the update itself is injected by name.
    dispatcher = Dispatcher(
        provider=ai_provider,
        avatars=avatars or AvatarProvider(),
        drafts=GroupDrafts(),
        images=images,
        offers=offers
        or PhotoOffers(
            ttl=settings.IMAGE_OFFER_TTL_SECONDS, cooldown=settings.IMAGE_OFFER_COOLDOWN_SECONDS
        ),
    )

    # Order matters: message ordering first (before any database work),
    # then the session, then the user that needs it.
    dispatcher.update.outer_middleware(ChatOrderMiddleware(locks or UserLocks()))
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_maker))
    dispatcher.update.outer_middleware(UserMiddleware())
    dispatcher.include_router(build_router())

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> bool:
        # Log the type only: exceptions can carry user text (SQL parameters).
        logger.error("Unhandled error while processing an update: %s", type(event.exception).__name__)
        await _tell_user_about_error(event)
        return True

    return dispatcher


async def _tell_user_about_error(event: ErrorEvent) -> None:
    """Best effort: a silent bot feels broken."""
    update = event.update
    try:
        if update.message is not None:
            language = update.message.from_user.language_code if update.message.from_user else None
            await update.message.answer(t(resolve_language(language), "error"))
        elif update.callback_query is not None:
            language = update.callback_query.from_user.language_code
            await update.callback_query.answer(t(resolve_language(language), "error"))
    except Exception as exc:
        logger.warning("Could not send the error notice: %s", type(exc).__name__)


async def set_commands(bot: Bot) -> None:
    """The "/" menu next to the message box, in English and Turkish."""
    try:
        for language in TEXTS:
            commands = [
                BotCommand(command=name, description=t(language, key)) for name, key in _COMMANDS
            ]
            if settings.IMAGES_ENABLED:
                commands.append(BotCommand(command="photo", description=t(language, "cmd_photo")))
                commands.append(BotCommand(command="gallery", description=t(language, "cmd_pictures")))
            await bot.set_my_commands(
                commands, language_code=None if language == "en" else language
            )
    except Exception as exc:
        logger.warning("Could not set the bot command menu: %s", type(exc).__name__)


async def run() -> None:
    from app.database.session import SessionLocal

    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to your .env file.")
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")

    provider = build_ai_provider()

    alert_handler = None
    admin_ids = parse_admin_ids(settings.ADMIN_TELEGRAM_IDS)

    await sync_characters_on_start(SessionLocal)

    bot = build_bot(settings.TELEGRAM_BOT_TOKEN)
    locks = UserLocks()  # shared: a character never talks over a live chat
    dispatcher = build_dispatcher(
        SessionLocal, ai_provider=provider, locks=locks, images=build_image_feature()
    )

    if admin_ids:
        alert_handler, send_alert = install_alerts(
            bot, admin_ids, settings.ALERT_DEDUP_SECONDS, settings.ALERT_MAX_PER_HOUR
        )
        await send_alert("✅ Bot started.")
        logger.info("Error alerts go to %d operator(s).", len(admin_ids))

    health_runner = None
    if settings.HEALTH_PORT:
        from app.telegram.health import start_health_server

        health_runner = await start_health_server(
            SessionLocal, provider, settings.HEALTH_HOST, settings.HEALTH_PORT
        )

    initiative_task = None
    if settings.INITIATIVE_ENABLED:
        initiative_task = asyncio.create_task(
            build_initiative_runner(bot, SessionLocal, provider, locks).run_forever()
        )
        logger.info("Characters may write first (opt-in users only).")

    try:
        await set_commands(bot)
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        if initiative_task is not None:
            initiative_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await initiative_task
        if health_runner is not None:
            await health_runner.cleanup()
        if alert_handler is not None:
            remove_alerts(alert_handler)
        await bot.session.close()
