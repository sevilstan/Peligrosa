"""Selling credits and subscriptions for Telegram Stars.

Flow: the user taps a product -> the bot sends an invoice (payload "buy:<key>")
-> Telegram asks us to approve it (pre-checkout, 10 seconds) -> after payment
Telegram sends successful_payment -> only THEN do we deliver.

Safety rules
- Delivery is idempotent: the Telegram charge id is unique, a repeated
  notification changes nothing.
- The payment record and what it bought are saved in ONE transaction.
- A payment for something no longer on sale is recorded as "needs_review"
  (never silently dropped, never guessed at).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.star_payment import StarPayment
from app.models.user import User
from app.services.credit_service import CreditConfig, CreditService

logger = logging.getLogger(__name__)

CURRENCY = "XTR"
PAYLOAD_PREFIX = "buy:"


@dataclass(frozen=True)
class Product:
    key: str
    stars: int
    credits: int = 0
    days: int = 0

    @property
    def is_subscription(self) -> bool:
        return self.days > 0


def parse_packs(text: str) -> list[Product]:
    """"100:50,300:125" -> packs of 100 credits for 50 Stars, ... Invalid
    entries are skipped with a warning so one typo cannot take the shop down."""
    products: dict[str, Product] = {}
    for entry in (text or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            credits_text, stars_text = entry.split(":")
            credits, stars = int(credits_text), int(stars_text)
        except ValueError:
            logger.warning("Ignoring an invalid CREDIT_PACKS entry.")
            continue
        if credits < 1 or stars < 1:
            logger.warning("Ignoring a CREDIT_PACKS entry with non-positive numbers.")
            continue
        key = f"pack{credits}"
        products.setdefault(key, Product(key=key, stars=stars, credits=credits))
    return list(products.values())


def build_catalog(settings) -> list[Product]:
    catalog = parse_packs(settings.CREDIT_PACKS)
    if settings.SUB_PRICE_STARS > 0 and settings.SUB_DAYS > 0:
        catalog.append(
            Product(
                key="sub",
                stars=settings.SUB_PRICE_STARS,
                credits=max(0, settings.SUB_BONUS_CREDITS),
                days=settings.SUB_DAYS,
            )
        )
    return catalog


def payload_for(product: Product) -> str:
    return PAYLOAD_PREFIX + product.key


@dataclass(frozen=True)
class Delivery:
    product: Product | None  # None: not on sale any more (needs review)
    duplicate: bool = False
    credits: int = 0
    subscription_until: datetime | None = None


class PaymentService:
    def __init__(self, session: AsyncSession, catalog: list[Product], credit_config: CreditConfig, clock=None):
        self.session = session
        self.catalog = {p.key: p for p in catalog}
        self.credit_config = credit_config
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def product_for_payload(self, payload: str) -> Product | None:
        if not isinstance(payload, str) or not payload.startswith(PAYLOAD_PREFIX):
            return None
        return self.catalog.get(payload[len(PAYLOAD_PREFIX):])

    def check_order(self, payload: str, currency: str, total: int) -> Product | None:
        """Pre-checkout: only what is on sale, at today's price, in Stars."""
        product = self.product_for_payload(payload)
        if product is None or currency != CURRENCY or total != product.stars:
            return None
        return product

    async def deliver(self, user_id, payload: str, total: int, charge_id: str) -> Delivery:
        product = self.product_for_payload(payload)
        credits = CreditService(self.session, self.credit_config, clock=self._clock)

        inserted = (
            await self.session.execute(
                pg_insert(StarPayment)
                .values(
                    user_id=user_id,
                    telegram_charge_id=charge_id,
                    product=(product.key if product else payload[:40]),
                    stars=total,
                    credits_granted=product.credits if product else 0,
                    days_granted=product.days if product else 0,
                    status="paid" if product else "needs_review",
                )
                .on_conflict_do_nothing(index_elements=[StarPayment.telegram_charge_id])
                .returning(StarPayment.id)
            )
        ).scalar_one_or_none()

        if inserted is None:
            await self.session.rollback()
            return Delivery(product=product, duplicate=True)

        if product is None:
            await self.session.commit()
            logger.error("Payment %s is for a product that is not on sale: needs review.", charge_id)
            return Delivery(product=None)

        user = await credits.apply_purchase(user_id, product.credits, product.days, product.key)
        await self.session.commit()
        return Delivery(
            product=product,
            credits=user.credits,
            subscription_until=user.subscription_until,
        )

    async def find(self, charge_id: str) -> tuple[StarPayment, int | None] | None:
        """The payment and its buyer's Telegram id."""
        row = (
            await self.session.execute(
                select(StarPayment, User.telegram_id)
                .join(User, User.id == StarPayment.user_id)
                .where(StarPayment.telegram_charge_id == charge_id)
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def reverse(self, charge_id: str) -> bool:
        """After Telegram refunded the Stars: take back what they bought.
        False when it was already refunded or is unknown."""
        payment = (
            await self.session.execute(
                select(StarPayment)
                .where(StarPayment.telegram_charge_id == charge_id)
                .with_for_update()
            )
        ).scalar_one_or_none()

        if payment is None or payment.status == "refunded":
            await self.session.rollback()
            return False

        await CreditService(self.session, self.credit_config, clock=self._clock).revoke_purchase(
            payment.user_id, payment.credits_granted, payment.days_granted, payment.product
        )
        payment.status = "refunded"
        payment.refunded_at = self._clock()
        await self.session.commit()
        return True
