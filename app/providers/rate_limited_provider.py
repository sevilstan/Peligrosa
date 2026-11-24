"""Keep AI traffic inside the provider's limits, for any AIProvider.

Free/cheap tiers allow only a few requests per minute (Groq free: 30). A group
message can cause several calls, so without a limit a handful of users would
trigger 429 errors. This wrapper

- lets at most `max_concurrent` calls run at once,
- starts at most `max_per_minute` calls in any 60 second window, making the
  rest WAIT in arrival order (the user just sees "typing..." a bit longer),
- gives up with RateLimitTimeout when the wait would exceed `max_wait`
  seconds, which callers already treat like any provider failure.

It is a limiter for THIS process only: run one bot process per API key.
"""

import asyncio
import logging
import time
from collections import deque

from app.providers.base import AIProvider

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60.0


class RateLimitTimeout(RuntimeError):
    """The AI request waited too long for a free slot."""


class RateLimitedProvider(AIProvider):
    def __init__(
        self,
        inner: AIProvider,
        max_per_minute: int,
        max_concurrent: int,
        max_wait: float,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    ):
        if max_per_minute < 1 or max_concurrent < 1 or max_wait <= 0:
            raise ValueError("Rate limits must be positive.")

        self.inner = inner
        self.max_per_minute = max_per_minute
        self.max_wait = max_wait
        self._clock = clock
        self._sleep = sleep
        self._starts: deque[float] = deque()
        self._turn = asyncio.Lock()  # FIFO: first to ask is first to start
        self._running = asyncio.Semaphore(max_concurrent)

    @property
    def model(self):
        return getattr(self.inner, "model", "?")

    async def generate_response(self, system_prompt: str, messages: list[dict]) -> str:
        try:
            async with asyncio.timeout(self.max_wait):
                await self._wait_for_slot()
        except TimeoutError as exc:
            logger.warning("AI request dropped: waited more than %ss for a free slot.", self.max_wait)
            raise RateLimitTimeout("AI rate limit queue is full.") from exc

        async with self._running:
            return await self.inner.generate_response(system_prompt, messages)

    async def _wait_for_slot(self) -> None:
        async with self._turn:
            while True:
                now = self._clock()
                while self._starts and now - self._starts[0] >= WINDOW_SECONDS:
                    self._starts.popleft()

                if len(self._starts) < self.max_per_minute:
                    self._starts.append(now)
                    return

                await self._sleep(self._starts[0] + WINDOW_SECONDS - now)
