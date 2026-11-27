"""Credits: the free trial, paid credits and subscriptions.

Rules
- CREDITS_ENABLED off: nothing is limited and nothing is recorded.
- A new user gets TRIAL_CREDITS once (granted lazily, so existing users get
  it too the first time they are checked).
- charge() locks the user's row, so two simultaneous messages can never spend
  the same credit. It COMMITS, so the charge is visible at once; if the work
  that was paid for fails, the caller calls refund().
- A subscriber (subscription_until in the future) spends no credits on things
  the subscription includes, but only SUB_DAILY_MESSAGE_CAP messages a
  day (protects the cost). Nothing a user wrote or the AI answered is stored
  here, only amounts and reasons.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credit_transaction import CreditTransaction
from app.models.user import User

MESSAGE_REASONS = ("message", "group_message")


class InsufficientCredits(Exception):
    """Not enough credits (and no active subscription) for this action."""

    def __init__(self, needed: int, available: int):
        super().__init__("Not enough credits.")
        self.needed = needed
        self.available = available


class DailyCapReached(Exception):
    """A subscriber used up today's message allowance."""


@dataclass(frozen=True)
class CreditConfig:
    enabled: bool = False
    trial: int = 10
    message_cost: int = 1
    group_message_cost: int = 2
    group_create_cost: int = 50
    image_cost: int = 5
    art_cost: int = 10
    subscriber_daily_cap: int = 100
    sub_group_create_free: bool = True

    @classmethod
    def from_settings(cls, settings) -> "CreditConfig":
        return cls(
            enabled=settings.CREDITS_ENABLED,
            trial=settings.TRIAL_CREDITS,
            message_cost=settings.MESSAGE_COST,
            group_message_cost=settings.GROUP_MESSAGE_COST,
            group_create_cost=settings.GROUP_CREATE_COST,
            image_cost=settings.IMAGE_COST,
            art_cost=settings.ART_COST,
            subscriber_daily_cap=max(1, settings.SUB_DAILY_MESSAGE_CAP),  # never unlimited
            sub_group_create_free=settings.SUB_GROUP_CREATE_FREE,
        )


@dataclass(frozen=True)
class Receipt:
    user_id: uuid.UUID
    amount: int  # credits actually spent (0 for free, disabled or subscriber)
    reason: str
    conversation_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CreditStatus:
    credits: int
    subscription_until: datetime | None
    subscribed: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CreditService:
    def __init__(self, session: AsyncSession, config: CreditConfig | None = None, clock=_now):
        self.session = session
        self.config = config or CreditConfig()
        self._clock = clock

    # ------------------------------------------------------------ reading

    async def status(self, user_id) -> CreditStatus:
        user = await self._lock_user(user_id, lock=False)
        return self._status(user)

    def _status(self, user: User) -> CreditStatus:
        until = user.subscription_until
        return CreditStatus(
            credits=user.credits,
            subscription_until=until,
            subscribed=bool(until and until > self._clock()),
        )

    async def ensure_trial(self, user_id) -> None:
        """Grant the one-time trial now (it is otherwise granted on first use)."""
        if not self.config.enabled:
            return
        user = await self._lock_user(user_id)
        self._grant_trial_if_due(user)
        await self.session.commit()

    # ------------------------------------------------------------- spending

    async def charge(
        self,
        user_id,
        cost: int,
        reason: str,
        conversation_id=None,
        included_in_subscription: bool = True,
    ) -> Receipt:
        if cost < 0:
            raise ValueError("Cost cannot be negative.")
        if not self.config.enabled or cost == 0:
            return Receipt(user_id, 0, reason, conversation_id)

        user = await self._lock_user(user_id)
        self._grant_trial_if_due(user)
        status = self._status(user)

        if status.subscribed and included_in_subscription:
            if reason in MESSAGE_REASONS and await self._messages_today(user_id) >= self.config.subscriber_daily_cap:
                await self.session.commit()  # keeps a freshly granted trial
                raise DailyCapReached()
            spent = 0
        else:
            if user.credits < cost:
                needed, available = cost, user.credits
                await self.session.commit()  # keeps a freshly granted trial
                raise InsufficientCredits(needed, available)
            user.credits -= cost
            spent = cost

        self._record(user, -spent, reason, conversation_id)
        await self.session.commit()
        return Receipt(user_id, spent, reason, conversation_id)

    async def refund(self, receipt: Receipt) -> None:
        """Give back what a failed action cost (no-op for free actions)."""
        if receipt.amount <= 0:
            return
        user = await self._lock_user(receipt.user_id)
        user.credits += receipt.amount
        self._record(user, receipt.amount, "refund", receipt.conversation_id)
        await self.session.commit()

    # ------------------------------------------------------------- granting

    async def grant(self, user_id, amount: int, reason: str = "admin_grant") -> int:
        if amount <= 0:
            raise ValueError("A grant must be positive.")
        user = await self._lock_user(user_id)
        user.credits += amount
        self._record(user, amount, reason)
        await self.session.commit()
        return user.credits

    async def apply_purchase(self, user_id, credits: int, days: int, product: str) -> User:
        """Add what a payment bought. Does NOT commit: the caller commits it
        together with the payment record, so one cannot exist without the other."""
        user = await self._lock_user(user_id)
        if credits:
            user.credits += credits
        if days:
            base = max(self._clock(), user.subscription_until or self._clock())
            user.subscription_until = base + timedelta(days=days)
        self._record(user, credits, f"buy_{product}"[:30])
        return user

    async def revoke_purchase(self, user_id, credits: int, days: int, product: str) -> None:
        """Take back what a refunded payment gave (credits never below 0, a
        subscription never ends earlier than now). Does not commit."""
        user = await self._lock_user(user_id)
        removed = min(credits, user.credits)
        user.credits -= removed
        if days and user.subscription_until and user.subscription_until > self._clock():
            user.subscription_until = max(
                self._clock(), user.subscription_until - timedelta(days=days)
            )
        self._record(user, -removed, f"refund_{product}"[:30])

    async def set_subscription(self, user_id, until: datetime | None) -> None:
        user = await self._lock_user(user_id)
        user.subscription_until = until
        await self.session.commit()

    # ------------------------------------------------------------ internals

    async def _lock_user(self, user_id, lock: bool = True) -> User:
        query = select(User).where(User.id == user_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        user = (await self.session.execute(query)).scalar_one_or_none()
        if user is None:
            raise ValueError("Unknown user.")
        return user

    def _grant_trial_if_due(self, user: User) -> None:
        if user.trial_granted_at is None:
            user.trial_granted_at = self._clock()
            user.credits += self.config.trial
            self._record(user, self.config.trial, "trial")

    def _record(self, user: User, amount: int, reason: str, conversation_id=None) -> None:
        self.session.add(
            CreditTransaction(
                user_id=user.id,
                amount=amount,
                balance_after=user.credits,
                reason=reason,
                conversation_id=conversation_id,
                created_at=self._clock(),
            )
        )

    async def _messages_today(self, user_id) -> int:
        start = self._clock().replace(hour=0, minute=0, second=0, microsecond=0)
        await self.session.flush()
        return (
            await self.session.execute(
                select(func.count())
                .select_from(CreditTransaction)
                .where(
                    CreditTransaction.user_id == user_id,
                    CreditTransaction.reason.in_(MESSAGE_REASONS),
                    CreditTransaction.created_at >= start,
                )
            )
        ).scalar_one()
