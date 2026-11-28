"""Make (or reuse) a picture of a character in the scene the chat is about.

Flow: the chat must be the user's own direct chat and the character must be
drawable -> the chat AI turns the recent chat into a few scene TAGS (untrusted
text; only known words survive, see image_scene) -> look in the cache for a
picture of this character with the same tags that this user has not received
yet -> otherwise ask the image provider (costs real money), store the picture
and remember it for the next user -> save a character message with the key.

Reuse keeps the picture variety honest: a scene gets IMAGE_CACHE_MIN_VARIANTS
different pictures before any is reused, and a user never gets the same
picture twice.
"""

import logging
import random
from dataclasses import dataclass

from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.image_cache import ImageCacheEntry
from app.models.message import Message
from app.providers.image_base import ImageProvider, image_extension
from app.services.character_definition_loader import CharacterDefinitionLoader
from app.services.conversation_service import ConversationService
from app.services.image_prompt_builder import ImageNotAvailable
from app.services.image_scene import SCENE_PROMPT, SceneTags, parse_scene
from app.services.image_storage import ImageStorage

logger = logging.getLogger(__name__)

SCENE_CONTEXT_MESSAGES = 6
# What the character's history says, so she knows she sent a photo.
HISTORY_TEXT = "*sends you a photo*"


@dataclass(frozen=True)
class ImageFeature:
    """Everything the bot needs when pictures are switched on."""

    provider: ImageProvider
    storage: ImageStorage
    loader: CharacterDefinitionLoader
    cache_min_variants: int = 2


@dataclass(frozen=True)
class PhotoResult:
    key: str
    data: bytes
    character_name: str
    from_cache: bool


def can_draw(feature: ImageFeature | None, slug: str) -> bool:
    """Pictures are on and this character has an image id and an adult age."""
    if feature is None:
        return False
    try:
        definition = feature.loader.load(slug)
    except ValueError:
        return False
    return bool(
        definition
        and definition.image_character_id
        and definition.profile
        and definition.profile.age is not None
    )


class ImageService:
    def __init__(self, session, feature: ImageFeature, chat_provider, rng: random.Random | None = None):
        self.session = session
        self.feature = feature
        self.chat_provider = chat_provider
        self.rng = rng or random.Random()

    async def generate(self, conversation_id, user_id, request_text: str | None) -> PhotoResult:
        """May raise ValueError (not the user's direct chat), ImageNotAvailable,
        or the provider's ImageGenerationError / ImageGenerationRefused."""
        conversation, character = await ConversationService(
            self.session, ai_provider=self.chat_provider
        ).get_direct_conversation(conversation_id, user_id)

        definition = self.feature.loader.load(character.slug)
        if definition is None or not definition.image_character_id:
            raise ImageNotAvailable(character.slug)

        tags = await self._tags(conversation.id, request_text)

        reused = await self._from_cache(character.id, tags, user_id)
        if reused is not None:
            key, data = reused
            from_cache = True
        else:
            data = await self.feature.provider.generate_image(
                tags.prompt(), character_ref=definition.image_character_id
            )
            key = await self.feature.storage.save(data, image_extension(data) or "png")
            self.session.add(ImageCacheEntry(character_id=character.id, scene_key=tags.key, image_key=key))
            from_cache = False

        self.session.add(
            Message(
                conversation_id=conversation.id,
                sender_type="character",
                sender_character_id=character.id,
                content=HISTORY_TEXT,
                message_type="image",
                image_key=key,
            )
        )
        await self.session.commit()
        return PhotoResult(key=key, data=data, character_name=definition.name, from_cache=from_cache)

    async def _from_cache(self, character_id, tags: SceneTags, user_id):
        """(key, bytes) of a stored picture this user has not got yet, or None."""
        wanted = self.feature.cache_min_variants
        if wanted <= 0:
            return None

        entries = (
            await self.session.execute(
                select(ImageCacheEntry).where(
                    ImageCacheEntry.character_id == character_id,
                    ImageCacheEntry.scene_key == tags.key,
                )
            )
        ).scalars().all()
        if len(entries) < wanted:
            return None  # first make enough different pictures of this scene

        seen = set(
            (
                await self.session.execute(
                    select(Message.image_key)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(
                        Conversation.user_id == user_id,
                        Message.image_key.in_([e.image_key for e in entries]),
                    )
                )
            ).scalars()
        )
        fresh = [e for e in entries if e.image_key not in seen]
        self.rng.shuffle(fresh)

        for entry in fresh:
            try:
                data = await self.feature.storage.load(entry.image_key)
            except FileNotFoundError:
                logger.warning("A cached picture file is missing; it is forgotten.")
                await self.session.delete(entry)
                continue
            except OSError:
                # Storage trouble is not proof the picture is gone: skip it,
                # keep the cache entry.
                logger.warning("A cached picture could not be read; skipped.")
                continue
            entry.use_count = (entry.use_count or 0) + 1
            return entry.image_key, data
        return None

    async def _tags(self, conversation_id, request_text: str | None) -> SceneTags:
        try:
            rows = (
                await self.session.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id, Message.message_type == "text")
                    .order_by(Message.created_at.desc(), Message.id.desc())
                    .limit(SCENE_CONTEXT_MESSAGES)
                )
            ).scalars().all()
            excerpt = "\n".join(
                f"{'User' if m.sender_type == 'user' else 'Her'}: {m.content[:300]}"
                for m in reversed(rows)
            )
            request = (request_text or "")[:300]
            reply = await self.chat_provider.generate_response(
                SCENE_PROMPT,
                [{"role": "user", "content": f"<chat>\n{excerpt}\n</chat>\n<request>{request}</request>"}],
            )
            return parse_scene(reply)
        except Exception:  # tags are a nicety: a default scene still works
            logger.warning("Scene tags failed; using the default scene.")
            return SceneTags()
