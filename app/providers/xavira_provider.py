"""Xavira (api.xavira.ai) as the image provider.

Xavira keeps the face and body of each person (a "character" made once in its
dashboard); we only send the character_id and a short scene prompt. A request
either finishes at once (201) or returns 202 and is polled. The finished
picture is downloaded from Xavira's storage host (https only, host checked).

All HTTP goes through a small transport object so tests can fake it. Prompts,
pictures and the API key are never logged.
"""

import asyncio
import json as json_module
import logging
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

from app.providers.image_base import (
    ImageGenerationError,
    ImageGenerationRefused,
    ImageProvider,
    image_extension,
)

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 15 * 1024 * 1024
POLL_INTERVAL_SECONDS = 2.0
LOW_BALANCE_WARN_INTERVAL_SECONDS = 6 * 3600
_STORAGE_HOST_SUFFIXES = (".r2.dev",)  # where Xavira serves pictures from
_FAILED_STATES = {"failed", "cancelled", "timed_out"}

# Tests replace this to avoid real waiting.
_sleep = asyncio.sleep


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict
    body: bytes
    json: dict | None = None


class AiohttpTransport:
    """The real network. One short-lived session per call keeps it simple."""

    def __init__(self, timeout: float = 60.0):
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def request(self, method, url, *, headers=None, json=None, max_bytes=1_000_000) -> HttpResponse:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.request(
                method, url, headers=headers, json=json, allow_redirects=False
            ) as response:
                body = await response.content.read(max_bytes + 1)
                parsed = None
                if response.content_type == "application/json":
                    try:
                        parsed = json_module.loads(body)
                    except ValueError:
                        parsed = None
                return HttpResponse(response.status, dict(response.headers), body, parsed)


class XaviraImageProvider(ImageProvider):
    name = "xavira"

    @property
    def model(self) -> str:
        return self.resolution

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.xavira.ai",
        resolution: str = "hd_portrait",
        max_wait: float = 60.0,
        low_balance: int = 5,
        transport=None,
        clock=time.monotonic,
    ):
        if not api_key:
            raise ValueError("XAVIRA_API_KEY is required.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.resolution = resolution
        self.max_wait = max_wait
        self.low_balance = low_balance
        self.transport = transport or AiohttpTransport(timeout=max_wait)
        self.clock = clock
        self.credits_remaining: int | None = None
        self._last_low_warning: float | None = None

    # ------------------------------------------------------------- public

    async def generate_image(self, prompt: str, character_ref: str | None = None) -> bytes:
        if not character_ref:
            raise ImageGenerationError("No Xavira character id for this character.")

        body = {"character_id": character_ref, "prompt": prompt, "resolution": self.resolution}
        response = await self._call(
            "POST",
            "/v1/images:generate",
            json=body,
            extra_headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        data = response.json or {}
        self._note_balance(data)

        if response.status == 202 or data.get("status") in ("pending", "processing", "running"):
            data = await self._wait_for(data)

        url = data.get("output_url")
        if data.get("status") != "completed" or not url:
            raise ImageGenerationError("Xavira returned no picture.")
        return await self._download(url)

    # ------------------------------------------------------------ helpers

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        headers.update(extra or {})
        return headers

    async def _call(self, method, path, *, json=None, extra_headers=None) -> HttpResponse:
        try:
            response = await self.transport.request(
                method, self.base_url + path, headers=self._headers(extra_headers), json=json
            )
        except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError) as exc:
            logger.warning("Xavira call failed: %s", type(exc).__name__)
            raise ImageGenerationError("Xavira could not be reached.") from exc

        if response.status >= 400:
            raise self._error_for(response)
        return response

    def _error_for(self, response: HttpResponse) -> ImageGenerationError:
        status = response.status
        code = ((response.json or {}).get("error") or {}).get("code", "")

        if status == 422 or code in ("moderation_blocked", "output_blocked"):
            return ImageGenerationRefused("Xavira declined this request.")
        if status == 401:
            logger.error("Xavira key was rejected: check XAVIRA_API_KEY.")
        elif status == 402:
            logger.error("Xavira is out of credit: add credit now.")
        elif status == 404 and code == "character_not_found":
            logger.error("Xavira does not know a character id from the YAML: check image_character_id.")
        else:
            logger.warning("Xavira returned status %s (%s).", status, code or "no code")
        return ImageGenerationError(f"Xavira returned status {status}.")

    async def _wait_for(self, data: dict) -> dict:
        generation_id = data.get("generation_id")
        if not generation_id:
            raise ImageGenerationError("Xavira did not say which picture is being made.")

        deadline = self.clock() + self.max_wait
        while True:
            await _sleep(POLL_INTERVAL_SECONDS)
            response = await self._call("GET", f"/v1/generations/{generation_id}")
            data = response.json or {}
            self._note_balance(data)

            status = data.get("status")
            if status == "completed":
                return data
            if status in _FAILED_STATES:
                raise ImageGenerationError("Xavira could not make the picture.")
            if self.clock() >= deadline:
                raise ImageGenerationError("Xavira took too long.")

    async def _download(self, url: str) -> bytes:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host.endswith(_STORAGE_HOST_SUFFIXES):
            logger.error("Xavira returned a picture link on an unexpected host.")
            raise ImageGenerationError("The picture link is not on Xavira's storage.")
        try:
            response = await self.transport.request(
                "GET", url, headers={}, max_bytes=MAX_IMAGE_BYTES
            )
        except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError) as exc:
            raise ImageGenerationError("The picture could not be downloaded.") from exc

        data = response.body
        if (
            response.status != 200
            or not data
            or len(data) > MAX_IMAGE_BYTES
            or image_extension(data) is None
        ):
            raise ImageGenerationError("The download is not a picture.")
        return data

    def _note_balance(self, data: dict) -> None:
        remaining = data.get("credits_remaining")
        if not isinstance(remaining, int):
            return
        self.credits_remaining = remaining
        if remaining >= self.low_balance:
            return
        now = self.clock()
        if self._last_low_warning is None or now - self._last_low_warning >= LOW_BALANCE_WARN_INTERVAL_SECONDS:
            self._last_low_warning = now
            logger.error("Xavira balance is low: %d credits left. Add credit soon.", remaining)
