"""Shared fakes for Telegram tests: no network, no bot token.

The aiogram HTTP session is replaced by a fake that records every API call;
payload helpers build updates the way Telegram sends them.
"""

import time
from pathlib import Path

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    EditMessageMedia,
    EditMessageText,
    RefundStarPayment,
    SendInvoice,
    SendMessage,
    SendPhoto,
)
from aiogram.types import Chat, Message, PhotoSize, Update
from sqlalchemy import func, select

from app.models import Character, User
from app.telegram.avatars import AvatarProvider
from app.telegram.bot import build_dispatcher
from tests.test_conversation_engine import ScriptedProvider

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201d4ccb9a40000000049454e44ae426082"
)


class FakeSession(BaseSession):
    """Records API calls instead of talking to Telegram."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, dict]] = []
        self.edit_text_error: str | None = None
        self.edit_media_error: str | None = None
        self.photo_error: str | None = None
        self.refund_error: str | None = None

    async def make_request(self, bot, method, timeout=None):
        data = method.model_dump(exclude_none=True)
        self.calls.append((type(method).__name__, data))

        if isinstance(method, EditMessageText) and self.edit_text_error:
            raise TelegramBadRequest(method=method, message=self.edit_text_error)
        if isinstance(method, EditMessageMedia) and self.edit_media_error:
            raise TelegramBadRequest(method=method, message=self.edit_media_error)
        if isinstance(method, SendPhoto) and self.photo_error:
            raise TelegramBadRequest(method=method, message=self.photo_error)

        if isinstance(method, RefundStarPayment) and self.refund_error:
            raise TelegramBadRequest(method=method, message=self.refund_error)

        if isinstance(method, (SendMessage, EditMessageText, SendPhoto, EditMessageMedia, SendInvoice)):
            photo = None
            if isinstance(method, (SendPhoto, EditMessageMedia)):
                photo = [PhotoSize(file_id="tg-file-id", file_unique_id="u", width=1, height=1)]
            return Message(
                message_id=500,
                date=int(time.time()),
                chat=Chat(id=data.get("chat_id", 1), type="private"),
                photo=photo,
            )
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    def named(self, name):
        return [data for call, data in self.calls if call == name]

    def names(self):
        return [call for call, _ in self.calls]


def _from(user_id, is_bot, first, lang):
    return {"id": user_id, "is_bot": is_bot, "first_name": first, "language_code": lang}


def message_update(text, *, user_id=1001, chat_type="private", is_bot=False, first="Ada", lang="en"):
    return {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "date": int(time.time()),
            "chat": {"id": user_id, "type": chat_type},
            "from": _from(user_id, is_bot, first, lang),
            "text": text,
        },
    }


def photo_message_update(*, user_id=1001, lang="en"):
    payload = message_update("x", user_id=user_id, lang=lang)
    del payload["message"]["text"]
    payload["message"]["photo"] = [{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}]
    return payload


def callback_update(data, *, user_id=1001, first="Ada", lang="en", has_photo=False):
    message = {
        "message_id": 20,
        "date": int(time.time()),
        "chat": {"id": user_id, "type": "private"},
    }
    if has_photo:
        message["photo"] = [{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}]
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb1",
            "chat_instance": "ci",
            "from": _from(user_id, False, first, lang),
            "data": data,
            "message": message,
        },
    }


def pre_checkout_update(payload, total, *, currency="XTR", user_id=1001, first="Ada", lang="en"):
    return {
        "update_id": 3,
        "pre_checkout_query": {
            "id": "pcq1",
            "from": _from(user_id, False, first, lang),
            "currency": currency,
            "total_amount": total,
            "invoice_payload": payload,
        },
    }


def successful_payment_update(payload, total, charge_id, *, user_id=1001, first="Ada", lang="en"):
    update = message_update("x", user_id=user_id, first=first, lang=lang)
    del update["message"]["text"]
    update["message"]["successful_payment"] = {
        "currency": "XTR",
        "total_amount": total,
        "invoice_payload": payload,
        "telegram_payment_charge_id": charge_id,
        "provider_payment_charge_id": "",
    }
    return update


class Harness:
    def __init__(self, maker, avatar_dir: Path, provider=None):
        self.maker = maker
        self.provider = provider or ScriptedProvider()
        self.session = FakeSession()
        self.bot = Bot(token="123456:TEST", session=self.session)
        self.avatar_dir = avatar_dir
        self.avatars = AvatarProvider(avatar_dir)
        self.dispatcher = build_dispatcher(maker, ai_provider=self.provider, avatars=self.avatars)

    async def send(self, payload):
        update = Update.model_validate(payload, context={"bot": self.bot})
        await self.dispatcher.feed_update(self.bot, update)

    def buttons(self, call_name="SendMessage", index=-1):
        markup = self.session.named(call_name)[index]["reply_markup"]
        return [b for row in markup["inline_keyboard"] for b in row]

    def callback_data(self, call_name="SendMessage", index=-1):
        return [b["callback_data"] for b in self.buttons(call_name, index)]

    def texts(self):
        return [d["text"] for d in self.session.named("SendMessage")]


async def add_characters(maker, specs, avatar_url=None):
    """specs: (name, slug, sort_order, is_active)"""
    async with maker() as session:
        for name, slug, sort_order, is_active in specs:
            session.add(
                Character(
                    name=name,
                    slug=slug,
                    description=f"About {name}",
                    personality="p",
                    system_prompt="You are a test character.",
                    sort_order=sort_order,
                    is_active=is_active,
                    avatar_url=avatar_url,
                )
            )
        await session.commit()


async def user_count(maker):
    async with maker() as session:
        return (await session.execute(select(func.count()).select_from(User))).scalar_one()
