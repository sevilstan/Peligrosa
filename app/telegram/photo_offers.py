"""Photo offers waiting for a yes or no.

Kept in memory on purpose: an offer is only a few minutes old, and after a
restart "this offer expired" is an honest, harmless answer. Each offer is
tied to the offer message and the user, and expires by itself.
"""

import time
import uuid
from dataclasses import dataclass

MAX_OFFERS = 1000


@dataclass(frozen=True)
class Offer:
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    request_text: str | None
    created: float


class PhotoOffers:
    def __init__(self, ttl: float = 900.0, cooldown: float = 60.0, clock=time.monotonic):
        self.ttl = ttl
        self.cooldown = cooldown
        self.clock = clock
        self._offers: dict[tuple[int, int], Offer] = {}
        self._last_offer: dict[uuid.UUID, float] = {}

    def add(self, chat_id: int, message_id: int, user_id, conversation_id, request_text: str | None) -> None:
        now = self.clock()
        self._prune(now)
        self._offers[(chat_id, message_id)] = Offer(user_id, conversation_id, request_text, now)
        self._last_offer[conversation_id] = now

    def get(self, chat_id: int, message_id: int) -> Offer | None:
        offer = self._offers.get((chat_id, message_id))
        if offer is not None and self.clock() - offer.created > self.ttl:
            del self._offers[(chat_id, message_id)]
            return None
        return offer

    def pop(self, chat_id: int, message_id: int) -> Offer | None:
        offer = self.get(chat_id, message_id)
        self._offers.pop((chat_id, message_id), None)
        return offer

    def recently_offered(self, conversation_id) -> bool:
        """For offers the bot makes by itself: not more than one per cooldown."""
        last = self._last_offer.get(conversation_id)
        return last is not None and self.clock() - last < self.cooldown

    def _prune(self, now: float) -> None:
        for key in [k for k, o in self._offers.items() if now - o.created > self.ttl]:
            del self._offers[key]
        while len(self._offers) >= MAX_OFFERS:
            del self._offers[next(iter(self._offers))]
        for conversation_id in [c for c, ts in self._last_offer.items() if now - ts > self.ttl]:
            del self._last_offer[conversation_id]
