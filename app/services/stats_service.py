"""A few numbers for the operator: users, sales, spending, pictures.

Counts only; no names, no message text. Shown by the operator-only /stats.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.credit_transaction import CreditTransaction
from app.models.image_cache import ImageCacheEntry
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
    pictures_made: int  # pictures that cost an image-service call
    pictures_reused: int  # served from the cache instead


class StatsService:
    def __init__(self, session, clock=lambda: datetime.now(timezone.utc)):
        self.session = session
        self.clock = clock

    async def collect(self) -> Stats:
        since = self.clock() - timedelta(hours=24)

        async def one(query) -> int:
            return int((await self.session.execute(query)).scalar() or 0)

        paid = StarPayment.status == "paid"
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
                select(func.count()).select_from(StarPayment).where(StarPayment.status != "paid")
            ),
            pictures_24h=await one(
                select(func.count()).select_from(Message).where(
                    Message.message_type == "image", Message.created_at >= since
                )
            ),
            pictures_made=await one(select(func.count()).select_from(ImageCacheEntry)),
            pictures_reused=await one(select(func.coalesce(func.sum(ImageCacheEntry.use_count), 0))),
        )


def format_stats(stats: Stats) -> str:
    total = stats.pictures_made + stats.pictures_reused
    saved = f"{round(100 * stats.pictures_reused / total)}%" if total else "-"
    return "\n".join(
        [
            "Last 24 hours",
            f"Users: {stats.users_total} total, {stats.users_new_24h} new, {stats.users_active_24h} active",
            f"Messages: {stats.messages_24h}",
            f"Credits spent: {stats.credits_spent_24h}",
            f"Stars earned: {stats.paid_stars_24h}",
            f"Pictures sent: {stats.pictures_24h}",
            "",
            "All time",
            f"Payments: {stats.paid_count} paid ({stats.paid_stars} Stars), {stats.refunded_count} refunded",
            f"Pictures: {stats.pictures_made} made, {stats.pictures_reused} reused ({saved} saved)",
        ]
    )
