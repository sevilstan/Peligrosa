"""Tell the operator when something breaks.

Every ERROR logged by our own code (logger names under "app.") becomes a short
Telegram message to the operators in ADMIN_TELEGRAM_IDS. That covers unhandled
errors, AI provider failures, and "payment received but not delivered".

Rules
- The text is only the logger name and the log message (we never log user text
  or secrets, see logging_config). No traceback is sent.
- The same problem is sent once per ALERT_DEDUP_SECONDS; the next message says
  how many similar ones were held back. At most ALERT_MAX_PER_HOUR in total,
  so a failure storm cannot flood the chat.
- Alerting can never break the bot or loop: it logs only at WARNING, ignores
  its own logger, and swallows send errors.
"""

import asyncio
import logging
import re
import time
from collections import deque
from typing import Callable

logger = logging.getLogger(__name__)

MAX_TEXT = 400
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]+")


def parse_admin_ids(text: str) -> list[int]:
    ids = []
    for part in (text or "").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit() and int(part) not in ids:
            ids.append(int(part))
    return ids


class AlertThrottle:
    def __init__(self, dedup_seconds: float, max_per_hour: int, clock=time.monotonic):
        self.dedup_seconds = dedup_seconds
        self.max_per_hour = max_per_hour
        self._clock = clock
        self._last_sent: dict[object, float] = {}
        self._held_back: dict[object, int] = {}
        self._sent_times: deque[float] = deque()

    def decide(self, key) -> int | None:
        """None: do not send. Otherwise send, and the number is how many
        similar alerts were held back since the last one."""
        now = self._clock()

        while self._sent_times and now - self._sent_times[0] >= 3600:
            self._sent_times.popleft()

        last = self._last_sent.get(key)
        if (last is not None and now - last < self.dedup_seconds) or (
            len(self._sent_times) >= self.max_per_hour
        ):
            self._held_back[key] = self._held_back.get(key, 0) + 1
            return None

        self._last_sent[key] = now
        self._sent_times.append(now)
        return self._held_back.pop(key, 0)


class AlertHandler(logging.Handler):
    def __init__(self, notify: Callable[[str], None], throttle: AlertThrottle):
        super().__init__(level=logging.ERROR)
        self.notify = notify
        self.throttle = throttle

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == __name__:
            return
        try:
            held_back = self.throttle.decide((record.name, str(record.msg)))
            if held_back is None:
                return

            message = _CONTROL.sub(" ", record.getMessage())[:MAX_TEXT]  # no traceback
            text = f"🚨 {record.name}\n{message}"
            if held_back:
                text += f"\n(+{held_back} similar held back)"
            self.notify(text)
        except Exception:  # alerting must never break the code that logged
            pass


def build_sender(bot, admin_ids: list[int]) -> Callable[[str], "asyncio.Future"]:
    async def send(text: str) -> None:
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, text, parse_mode=None)
            except Exception as exc:
                # Usually: the operator never pressed /start in the bot.
                logger.warning("Could not send an alert: %s", type(exc).__name__)

    return send


def install_alerts(bot, admin_ids: list[int], dedup_seconds: float, max_per_hour: int):
    """Attach the alert handler to our loggers. Returns (handler, send);
    call remove_alerts(handler) on shutdown."""
    loop = asyncio.get_running_loop()
    send = build_sender(bot, admin_ids)
    pending: set[asyncio.Task] = set()

    def schedule(text: str) -> None:
        def start() -> None:
            task = asyncio.ensure_future(send(text))
            pending.add(task)
            task.add_done_callback(pending.discard)

        loop.call_soon_threadsafe(start)

    handler = AlertHandler(schedule, AlertThrottle(dedup_seconds, max_per_hour))
    logging.getLogger("app").addHandler(handler)
    return handler, send


def remove_alerts(handler: logging.Handler) -> None:
    logging.getLogger("app").removeHandler(handler)
