"""The operator's /stats numbers, and who may see them."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.core.config import settings
from app.models import CreditTransaction, ImageCacheEntry, ImageGeneration, Message, StarPayment, User
from app.services.stats_service import StatsService, format_stats
from app.telegram.texts import t
from tests.telegram_harness import Harness, add_characters, callback_update, message_update
from tests.test_conversation_engine import seed_conversation

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
RECENT = NOW - timedelta(hours=2)
OLD = NOW - timedelta(days=3)


async def seed(maker):
    """One user with recent and old activity, payments, credits and pictures."""
    user_id, character_id, conv_id = await seed_conversation(maker)
    async with maker() as s:
        await s.execute(update(User).where(User.id == user_id).values(created_at=OLD))
        s.add(User(email="new@example.test", language_code="en", created_at=RECENT))
        silent = User(email="silent@example.test", language_code="en", created_at=OLD)
        s.add(silent)
        await s.flush()
        s.add(  # wrote only long ago: a user, but not an active one
            Message(
                conversation_id=conv_id, sender_type="user", sender_user_id=silent.id,
                content="old", message_type="text", created_at=OLD,
            )
        )

        def msg(kind, created, **kw):
            return Message(
                conversation_id=conv_id,
                sender_type="user" if kind == "user" else "character",
                sender_user_id=user_id if kind == "user" else None,
                sender_character_id=None if kind == "user" else character_id,
                content="a private sentence",
                message_type=kw.get("message_type", "text"),
                image_key=kw.get("image_key"),
                created_at=created,
            )

        s.add_all(
            [
                msg("user", RECENT),
                msg("user", RECENT),
                msg("user", OLD),
                msg("character", RECENT),
                msg("character", RECENT, message_type="image", image_key="a.png"),
                msg("character", OLD, message_type="image", image_key="b.png"),
            ]
        )
        for charge_id, stars, status, created in [
            ("c1", 50, "paid", RECENT),
            ("c2", 100, "paid", OLD),
            ("c3", 25, "refunded", RECENT),
            ("c4", 75, "needs_review", RECENT),  # not a refund
        ]:
            s.add(
                StarPayment(
                    user_id=user_id, telegram_charge_id=charge_id, product="pack", stars=stars,
                    status=status, created_at=created,
                )
            )
        for amount, created in [(-1, RECENT), (-5, RECENT), (-1, OLD), (50, RECENT)]:
            s.add(CreditTransaction(user_id=user_id, amount=amount, balance_after=0, reason="x", created_at=created))
        s.add(ImageCacheEntry(character_id=character_id, scene_key="k", image_key="a.png", use_count=3))
        s.add(ImageCacheEntry(character_id=character_id, scene_key="k", image_key="b.png", use_count=1))
        for source, status, created, cost in [
            ("provider", "ok", RECENT, 2.0),
            ("provider", "ok", OLD, 2.0),
            ("provider", "refused", RECENT, 2.0),
            ("cache", "ok", RECENT, None),
        ]:
            s.add(
                ImageGeneration(
                    user_id=user_id, character_id=character_id, kind="photo", source=source,
                    status=status, provider="xavira", cost=cost, created_at=created,
                )
            )
        await s.commit()


def test_the_numbers_count_the_last_day_and_all_time(run_db):
    async def scenario(maker):
        await seed(maker)
        async with maker() as s:
            stats = await StatsService(s, clock=lambda: NOW).collect()

        assert (stats.users_total, stats.users_new_24h, stats.users_active_24h) == (3, 1, 1)
        assert stats.messages_24h == 2  # only user messages, only the last day
        assert stats.credits_spent_24h == 6  # spending only: -1 and -5, not the +50 or the old -1
        assert (stats.paid_count, stats.paid_stars, stats.paid_stars_24h, stats.refunded_count) == (2, 150, 50, 1)
        assert stats.pictures_24h == 1
        assert (stats.cached_images, stats.cache_reuse_count) == (2, 4)
        assert (stats.provider_calls, stats.provider_calls_24h, stats.provider_failed) == (3, 2, 1)
        assert stats.cache_hits == 1 and stats.provider_cost == 6.0
        assert len(stats.top_characters) == 1 and stats.top_characters[0][1:] == (3, 6.0)

    run_db(scenario)


def test_the_report_is_readable_and_has_no_private_text(run_db):
    async def scenario(maker):
        await seed(maker)
        async with maker() as s:
            text = format_stats(await StatsService(s, clock=lambda: NOW).collect())

        assert "Users: 3 total, 1 new, 1 active" in text
        assert "1 refunded" in text and "2 paid (150 Stars)" in text
        assert "Image-service calls: 3 (1 refused/failed), cache hits: 1 (25% served from cache)" in text
        assert "Unique cached images: 2, cache reuse count: 4" in text
        assert "Recorded image cost: 6" in text
        assert "private sentence" not in text and "example.test" not in text

    run_db(scenario)


def test_an_empty_database_gives_zeros_not_errors(run_db):
    async def scenario(maker):
        async with maker() as s:
            text = format_stats(await StatsService(s).collect())
        assert "Users: 0 total" in text and "(- served from cache)" in text

    run_db(scenario)


def test_only_operators_can_open_stats(run_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_IDS", "1001")

    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/stats", user_id=2002, first="Bo"))
        assert bot.texts()[-1] == t("en", "unknown_command")

        await bot.send(message_update("/stats", user_id=1001))
        assert bot.texts()[-1].startswith("Last 24 hours") and "Users:" in bot.texts()[-1]

    run_db(scenario)


def test_credits_tells_an_operator_that_nothing_is_charged(run_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CREDITS_ENABLED", True)
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_IDS", "1001")

    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/credits", user_id=1001))
        assert bot.texts()[-1] == "Operator account: nothing is charged to you."

        await bot.send(message_update("/credits", user_id=2002, first="Bo"))
        assert bot.texts()[-1] != "Operator account: nothing is charged to you."

    run_db(scenario)


def test_characters_are_ranked_by_image_service_calls(run_db):
    async def scenario(maker):
        from app.models import Character

        await seed(maker)  # the seeded character has 3 provider calls
        async with maker() as s:
            busy = Character(name="Aaa", slug="aaa", description="d", personality="p", system_prompt="s")
            s.add(busy)
            await s.flush()
            for _ in range(5):
                s.add(ImageGeneration(character_id=busy.id, kind="art", source="provider", status="ok", provider="x"))
            await s.commit()
            stats = await StatsService(s, clock=lambda: NOW).collect()
        assert [(n, c) for n, c, _ in stats.top_characters][0] == ("Aaa", 5)
        assert len(stats.top_characters) == 2

    run_db(scenario)
