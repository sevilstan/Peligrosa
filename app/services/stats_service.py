"""A few numbers for the operator: users, sales, spending, pictures.

Counts only; no names, no message text. Shown by the operator-only /stats.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.credit_transaction import CreditTransaction
from app.models.character import Character
from app.models.image_cache import ImageCacheEntry
from app.models.image_generation import ImageGeneration
from app.models.message import Message
from app.models.star_payment import StarPayment
from app.models.user import User


@dataclass(frozen=True)
class Stats:
    users_total: int
    users_new_24h: int
    users_active_24h: int
    messages_24h: int
    credits_spent_24h: int
    paid_count: int
    paid_stars: int
    paid_stars_24h: int
    refunded_count: int
    pictures_24h: int
    cached_images: int  # distinct pictures stored in the cache
    cache_reuse_count: int  # how often stored pictures were handed out again
    provider_calls: int  # image-service calls, from the cost ledger (all attempts)
    provider_calls_24h: int
    provider_failed: int  # refused or failed calls (credits were refunded)
    cache_hits: int  # pictures served from the cache, from the ledger
    provider_cost: float  # sum of recorded cost (0 when XAVIRA_COST_PER_IMAGE is unset)
    top_characters: tuple[tuple[str, int, float], ...] = ()  # (name, calls, cost)


class StatsService:
    def __init__(self, session, clock=lambda: datetime.now(timezone.utc)):
        self.session = session
        self.clock = clock

    async def collect(self) -> Stats:
        since = self.clock() - timedelta(hours=24)

        async def one(query) -> int:
            return int((await self.session.execute(query)).scalar() or 0)

        paid = StarPayment.status == "paid"
        called = ImageGeneration.source == "provider"
        return Stats(
            users_total=await one(select(func.count()).select_from(User)),
            users_new_24h=await one(select(func.count()).select_from(User).where(User.created_at >= since)),
            users_active_24h=await one(
                select(func.count(func.distinct(Message.sender_user_id))).where(
                    Message.sender_user_id.is_not(None), Message.created_at >= since
                )
            ),
            messages_24h=await one(
                select(func.count()).select_from(Message).where(
                    Message.sender_user_id.is_not(None), Message.created_at >= since
                )
            ),
            credits_spent_24h=-await one(
                select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                    CreditTransaction.amount < 0, CreditTransaction.created_at >= since
                )
            ),
            paid_count=await one(select(func.count()).select_from(StarPayment).where(paid)),
            paid_stars=await one(select(func.coalesce(func.sum(StarPayment.stars), 0)).where(paid)),
            paid_stars_24h=await one(
                select(func.coalesce(func.sum(StarPayment.stars), 0)).where(paid, StarPayment.created_at >= since)
            ),
            refunded_count=await one(
                select(func.count()).select_from(StarPayment).where(StarPayment.status == "refunded")
            ),
            pictures_24h=await one(
                select(func.count()).select_from(Message).where(
                    Message.message_type == "image", Message.created_at >= since
                )
            ),
            cached_images=await one(select(func.count()).select_from(ImageCacheEntry)),
            cache_reuse_count=await one(select(func.coalesce(func.sum(ImageCacheEntry.use_count), 0))),
            provider_calls=await one(select(func.count()).select_from(ImageGeneration).where(called)),
            provider_calls_24h=await one(
                select(func.count()).select_from(ImageGeneration).where(called, ImageGeneration.created_at >= since)
            ),
            provider_failed=await one(
                select(func.count()).select_from(ImageGeneration).where(called, ImageGeneration.status != "ok")
            ),
            cache_hits=await one(
                select(func.count()).select_from(ImageGeneration).where(ImageGeneration.source == "cache")
            ),
            provider_cost=float(
                (await self.session.execute(select(func.coalesce(func.sum(ImageGeneration.cost), 0)))).scalar() or 0
            ),
            top_characters=await self._top_characters(called),
        )

    async def _top_characters(self, called) -> tuple[tuple[str, int, float], ...]:
        rows = (
            await self.session.execute(
                select(
                    Character.name,
                    func.count(),
                    func.coalesce(func.sum(ImageGeneration.cost), 0),
                )
                .join(Character, Character.id == ImageGeneration.character_id)
                .where(called)
                .group_by(Character.name)
                .order_by(func.count().desc(), Character.name)
                .limit(5)
            )
        ).all()
        return tuple((name, int(calls), float(cost)) for name, calls, cost in rows)


def format_stats(stats: Stats) -> str:
    served = stats.provider_calls + stats.cache_hits
    saved = f"{round(100 * stats.cache_hits / served)}%" if served else "-"
    lines = [
        "Last 24 hours",
        f"Users: {stats.users_total} total, {stats.users_new_24h} new, {stats.users_active_24h} active",
        f"Messages: {stats.messages_24h}",
        f"Credits spent: {stats.credits_spent_24h}",
        f"Stars earned: {stats.paid_stars_24h}",
        f"Pictures sent: {stats.pictures_24h}",
        f"Image-service calls: {stats.provider_calls_24h}",
        "",
        "All time",
        f"Payments: {stats.paid_count} paid ({stats.paid_stars} Stars), {stats.refunded_count} refunded",
        f"Image-service calls: {stats.provider_calls} ({stats.provider_failed} refused/failed), "
        f"cache hits: {stats.cache_hits} ({saved} served from cache)",
        f"Unique cached images: {stats.cached_images}, cache reuse count: {stats.cache_reuse_count}",
        f"Recorded image cost: {stats.provider_cost:g}"
        + ("" if stats.provider_cost else " (set XAVIRA_COST_PER_IMAGE to record it)"),
    ]
    if stats.top_characters:
        lines.append("Most image-service calls: " + ", ".join(
            f"{name} {calls}" + (f" ({cost:g})" if cost else "") for name, calls, cost in stats.top_characters
        ))
    return "\n".join(lines)
