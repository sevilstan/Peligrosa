"""Count AI traffic, for any AIProvider, so cost and trouble are visible.

Keeps per-day counters (UTC date) in memory: calls, failures, total seconds
and the size of prompts/answers in characters (providers do not report tokens
through our interface, characters are a good enough trend indicator). Counters
restart with the process; they are for watching, not for billing.

Never stores prompt or answer text.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.providers.base import AIProvider

logger = logging.getLogger(__name__)

KEEP_DAYS = 7


@dataclass
class DayUsage:
    calls: int = 0
    failures: int = 0
    seconds: float = 0.0
    prompt_chars: int = 0
    answer_chars: int = 0


class UsageTrackingProvider(AIProvider):
    def __init__(self, inner: AIProvider, clock=time.monotonic, today=None):
        self.inner = inner
        self._clock = clock
        self._today = today or (lambda: datetime.now(timezone.utc).date().isoformat())
        self.days: dict[str, DayUsage] = {}

    @property
    def model(self):
        return getattr(self.inner, "model", "?")

    async def generate_response(self, system_prompt: str, messages: list[dict]) -> str:
        usage = self._usage()
        usage.calls += 1
        usage.prompt_chars += len(system_prompt) + sum(len(str(m.get("content", ""))) for m in messages)
        started = self._clock()

        try:
            answer = await self.inner.generate_response(system_prompt, messages)
        except Exception as exc:
            usage.failures += 1
            # One (deduplicated) alert for the operator; type only, never text.
            logger.error("AI provider call failed: %s", type(exc).__name__)
            raise
        finally:
            usage.seconds += self._clock() - started

        usage.answer_chars += len(answer or "")
        return answer

    def _usage(self) -> DayUsage:
        day = self._today()
        if day not in self.days:
            self.days[day] = DayUsage()
            for old in sorted(self.days)[:-KEEP_DAYS]:
                del self.days[old]
        return self.days[day]

    def snapshot(self) -> dict:
        return {
            day: {
                "calls": u.calls,
                "failures": u.failures,
                "avg_seconds": round(u.seconds / u.calls, 2) if u.calls else 0.0,
                "prompt_chars": u.prompt_chars,
                "answer_chars": u.answer_chars,
            }
            for day, u in sorted(self.days.items())
        }
