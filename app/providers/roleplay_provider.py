"""Roleplay API (api.roleplayapi.com): an OpenAI-compatible chat endpoint.

Same call shape as the other providers, plus two operator aids taken from the
service's own signals:
- HTTP 402 (out of credit) and 401 (key rejected) are logged as ERRORs, which
  become operator alerts (see app/core/alerts.py);
- the X-Balance-USD response header is watched, and a low balance is logged as
  an ERROR (at most once every few hours) BEFORE the credit runs out.

Neither the prompt nor the reply is ever logged.
"""

import logging
import time

import openai
from openai import AsyncOpenAI

from app.core.config import settings
from app.providers.base import AIProvider

logger = logging.getLogger(__name__)

LOW_BALANCE_WARN_INTERVAL_SECONDS = 6 * 3600


class RoleplayProvider(AIProvider):
    def __init__(self, model: str | None = None, client=None, clock=time.monotonic):
        if client is None and not settings.ROLEPLAY_API_KEY:
            raise RuntimeError("ROLEPLAY_API_KEY is not set. Add it to your .env file.")

        self.model = model or settings.ROLEPLAY_MODEL
        self.client = client or AsyncOpenAI(
            api_key=settings.ROLEPLAY_API_KEY,
            base_url=settings.ROLEPLAY_BASE_URL,
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            max_retries=settings.AI_MAX_RETRIES,
        )
        self.balance_usd: float | None = None
        self._clock = clock
        self._last_low_balance_warning: float | None = None

    async def generate_response(self, system_prompt: str, messages: list[dict]) -> str:
        try:
            raw = await self.client.chat.completions.with_raw_response.create(
                model=self.model,
                messages=[{"role": "system", "content": system_prompt}, *messages],
                temperature=0.8,
                max_tokens=1000,
            )
        except openai.APIStatusError as exc:
            if exc.status_code == 402:
                logger.error("Roleplay API is out of credit: add credit now.")
            elif exc.status_code == 401:
                logger.error("Roleplay API key was rejected: check ROLEPLAY_API_KEY.")
            raise

        self._watch_balance(raw.headers.get("X-Balance-USD"))
        response = raw.parse()
        return response.choices[0].message.content or ""

    def _watch_balance(self, header: str | None) -> None:
        try:
            balance = float(header)
        except (TypeError, ValueError):
            return
        if balance != balance:  # NaN
            return

        self.balance_usd = balance
        if balance >= settings.ROLEPLAY_LOW_BALANCE_USD:
            return

        now = self._clock()
        last = self._last_low_balance_warning
        if last is None or now - last >= LOW_BALANCE_WARN_INTERVAL_SECONDS:
            self._last_low_balance_warning = now
            logger.error("Roleplay API balance is low: $%.2f left. Add credit soon.", balance)
