"""Making and reusing pictures."""

import random

import pytest
from sqlalchemy import func, select

from app.models import Character, Conversation, ImageCacheEntry, ImageGeneration, Message, User
from app.providers.image_base import ImageGenerationError
from app.services.conversation_service import ConversationService
from app.services.image_prompt_builder import ImageNotAvailable
from app.services.image_service import HISTORY_TEXT, ImageFeature, ImageService, can_draw
from app.services.image_storage import LocalImageStorage
from tests.image_fakes import BrokenImageProvider, FakeImageProvider, FakeLoader, SceneProvider, definition
from tests.test_conversation_engine import ScriptedProvider, add_messages, seed_conversation


def feature(tmp_path, provider=None, variants=2, loader=None):
    return ImageFeature(
        provider=provider or FakeImageProvider(),
        storage=LocalImageStorage(tmp_path / "images"),
        loader=loader or FakeLoader(definition()),
        cache_min_variants=variants,
    )


async def another_chat(maker, character_id, email):
    async with maker() as session:
        user = User(email=email, language_code="tr")
        session.add(user)
        await session.commit()
        conversation = await ConversationService(session, ai_provider=ScriptedProvider()).create_conversation(
            user.id, character_id
        )
        return user.id, conversation.id


async def photo(maker, feat, user_id, conversation_id, chat=None, request="send a pic", deliver=True):
    """Make a picture; by default as if Telegram delivered it (confirm_delivery)."""
    async with maker() as session:
        service = ImageService(session, feat, chat or SceneProvider(), rng=random.Random(1))
        result = await service.generate(conversation_id, user_id, request)
        if deliver:
            await service.confirm_delivery(result)
        return result


async def count(maker, model):
    async with maker() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


def test_a_new_scene_is_made_stored_cached_and_saved_in_the_chat(run_db, tmp_path):
    async def scenario(maker):
        user_id, character_id, conv_id = await seed_conversation(maker)
        await add_messages(maker, conv_id, user_id, character_id, 4)
        feat = feature(tmp_path)

        result = await photo(maker, feat, user_id, conv_id)

        assert result.from_cache is False and result.character_name == "Testa"
        assert feat.provider.calls == [
            ("lying down, in a bedroom, wearing red dress, natural light, candid photo", "xav-test-1234")
        ]
        assert await feat.storage.load(result.key) == result.data

        async with maker() as s:
            message = (await s.execute(select(Message).where(Message.image_key == result.key))).scalar_one()
            assert (message.message_type, message.sender_type, message.content) == ("image", "character", HISTORY_TEXT)
            entry = (await s.execute(select(ImageCacheEntry))).scalar_one()
            assert entry.scene_key == "bedroom|lying down|red dress" and entry.image_key == result.key

    run_db(scenario)


def test_nothing_the_user_typed_reaches_the_image_service(run_db, tmp_path):
    async def scenario(maker):
        user_id, character_id, conv_id = await seed_conversation(maker)
        await add_messages(maker, conv_id, user_id, character_id, 2)
        feat = feature(tmp_path)
        chat = SceneProvider(scene_reply="setting=cafe; pose=sitting; outfit=blue top; extra=hunter2")

        await photo(maker, feat, user_id, conv_id, chat=chat, request="my password is hunter2")

        prompt, _ = feat.provider.calls[0]
        assert "hunter2" not in prompt and "password" not in prompt
        assert "hunter2" in chat.scene_requests[0][0]["content"]  # only the scene writer saw the chat

    run_db(scenario)


def test_a_scene_is_made_twice_before_it_is_reused_for_someone_else(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        b, conv_b = await another_chat(maker, character_id, "b@example.test")
        c, conv_c = await another_chat(maker, character_id, "c@example.test")
        feat = feature(tmp_path, variants=2)

        first = await photo(maker, feat, a, conv_a)
        second = await photo(maker, feat, b, conv_b)
        third = await photo(maker, feat, c, conv_c)

        assert [first.from_cache, second.from_cache, third.from_cache] == [False, False, True]
        assert len(feat.provider.calls) == 2  # the third user cost nothing
        assert third.key in {first.key, second.key}
        async with maker() as s:
            used = (await s.execute(select(ImageCacheEntry.use_count))).scalars().all()
            assert sorted(used) == [0, 1]

    run_db(scenario)


def test_nobody_gets_the_same_picture_twice(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        feat = feature(tmp_path, variants=1)

        first = await photo(maker, feat, a, conv_a)
        again = await photo(maker, feat, a, conv_a)  # a has seen the only one: make a new one

        assert again.from_cache is False and again.key != first.key
        assert len(feat.provider.calls) == 2
        assert await count(maker, ImageCacheEntry) == 2

    run_db(scenario)


def test_reuse_can_be_switched_off(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        b, conv_b = await another_chat(maker, character_id, "b@example.test")
        feat = feature(tmp_path, variants=0)

        await photo(maker, feat, a, conv_a)
        second = await photo(maker, feat, b, conv_b)

        assert second.from_cache is False and len(feat.provider.calls) == 2

    run_db(scenario)


def test_pictures_are_never_shared_between_characters_or_scenes(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        async with maker() as s:
            other = Character(name="Other", slug="other", description="d", personality="p", system_prompt="s")
            s.add(other)
            await s.commit()
            other_id = other.id
        b, conv_b = await another_chat(maker, other_id, "b@example.test")
        feat = feature(tmp_path, variants=1, loader=FakeLoader(definition(), definition("other", "Other", image_id="xav-other-1234")))

        await photo(maker, feat, a, conv_a)
        other_char = await photo(maker, feat, b, conv_b)
        c, conv_c = await another_chat(maker, character_id, "c@example.test")
        different_scene = await photo(
            maker, feat, c, conv_c, chat=SceneProvider(scene_reply="setting=beach; pose=walking; outfit=white shirt")
        )

        assert not other_char.from_cache and not different_scene.from_cache
        assert [ref for _, ref in feat.provider.calls] == ["xav-test-1234", "xav-other-1234", "xav-test-1234"]

    run_db(scenario)


def test_a_missing_cached_file_is_forgotten_and_the_picture_is_made_again(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        b, conv_b = await another_chat(maker, character_id, "b@example.test")
        feat = feature(tmp_path, variants=1)

        first = await photo(maker, feat, a, conv_a)
        (tmp_path / "images" / first.key).unlink()
        second = await photo(maker, feat, b, conv_b)

        assert second.from_cache is False and second.key != first.key
        assert await count(maker, ImageCacheEntry) == 1

    run_db(scenario)


def test_a_storage_outage_does_not_forget_cached_pictures(run_db, tmp_path):
    from app.services.image_storage import ImageStorageError

    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        b, conv_b = await another_chat(maker, character_id, "b@example.test")
        feat = feature(tmp_path, variants=1)

        first = await photo(maker, feat, a, conv_a)

        real_load = feat.storage.load

        async def broken(key):
            raise ImageStorageError("storage is down")

        feat.storage.load = broken
        await photo(maker, feat, b, conv_b)  # falls back to making a new one
        feat.storage.load = real_load

        # The first picture is still in the cache: an outage is not "file gone".
        assert await count(maker, ImageCacheEntry) == 2
        assert (await real_load(first.key))

    run_db(scenario)


def test_a_failing_scene_writer_still_gives_a_default_picture(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        feat = feature(tmp_path)
        chat = SceneProvider()
        chat.scene_fails = True

        await photo(maker, feat, a, conv_a, chat=chat)

        assert feat.provider.calls[0][0].startswith("taking a selfie, at home")

    run_db(scenario)


def test_provider_failure_leaves_no_trace(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        feat = feature(tmp_path, provider=BrokenImageProvider())

        with pytest.raises(ImageGenerationError):
            await photo(maker, feat, a, conv_a)

        assert await count(maker, ImageCacheEntry) == 0
        assert not (tmp_path / "images").exists() or not list((tmp_path / "images").iterdir())
        async with maker() as s:
            images = (await s.execute(select(func.count()).select_from(Message).where(Message.message_type == "image"))).scalar_one()
            assert images == 0

    run_db(scenario)


def test_only_a_drawable_character_in_your_own_direct_chat(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        b, conv_b = await another_chat(maker, character_id, "b@example.test")

        with pytest.raises(ImageNotAvailable):
            await photo(maker, feature(tmp_path, loader=FakeLoader()), a, conv_a)  # no definition
        with pytest.raises(ImageNotAvailable):
            await photo(maker, feature(tmp_path, loader=FakeLoader(definition(image_id=""))), a, conv_a)
        with pytest.raises(ValueError):
            await photo(maker, feature(tmp_path), a, conv_b)  # someone else's chat

    run_db(scenario)


def test_can_draw_needs_an_image_id_and_an_adult_age(tmp_path):
    assert can_draw(feature(tmp_path), "test-char")
    assert not can_draw(None, "test-char")
    assert not can_draw(feature(tmp_path, loader=FakeLoader()), "test-char")
    assert not can_draw(feature(tmp_path, loader=FakeLoader(definition(image_id=""))), "test-char")
    assert not can_draw(feature(tmp_path, loader=FakeLoader(definition(age=None))), "test-char")


def test_nothing_joins_the_chat_until_delivery_is_confirmed(run_db, tmp_path):
    async def scenario(maker):
        user_id, character_id, conv_id = await seed_conversation(maker)
        await add_messages(maker, conv_id, user_id, character_id, 4)
        feat = feature(tmp_path, variants=1)

        made = await photo(maker, feat, user_id, conv_id, deliver=False)  # Telegram never delivered it
        assert await count(maker, ImageCacheEntry) == 1  # the picture itself is kept for others
        async with maker() as s:
            assert (await s.execute(select(Message).where(Message.message_type == "image"))).first() is None

        # The user never received it, so it is still fresh for them: reused, not remade.
        again = await photo(maker, feat, user_id, conv_id, deliver=False)
        assert again.from_cache and again.key == made.key and len(feat.provider.calls) == 1
        async with maker() as s:
            assert (await s.execute(select(ImageCacheEntry.use_count))).scalar_one() in (0, None)

        async with maker() as session:  # now one is delivered
            await ImageService(session, feat, SceneProvider()).confirm_delivery(again)
        async with maker() as s:
            assert (await s.execute(select(ImageCacheEntry.use_count))).scalar_one() == 1
            assert len((await s.execute(select(Message).where(Message.message_type == "image"))).all()) == 1

    run_db(scenario)


async def forget_chat_pictures(maker):
    """What deleting a chat does to the pictures in it: the messages are gone."""
    from sqlalchemy import delete

    async with maker() as s:
        await s.execute(delete(Message).where(Message.message_type == "image"))
        await s.commit()


def test_a_user_never_gets_a_picture_again_even_after_deleting_the_chat(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        feat = feature(tmp_path, variants=1)

        first = await photo(maker, feat, a, conv_a)
        await forget_chat_pictures(maker)  # the chat (and its messages) were deleted
        again = await photo(maker, feat, a, conv_a)

        assert again.from_cache is False and again.key != first.key
        assert len(feat.provider.calls) == 2

    run_db(scenario)


def test_a_cache_match_is_remembered_for_the_user_it_was_sent_to(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        b, conv_b = await another_chat(maker, character_id, "b@example.test")
        feat = feature(tmp_path, variants=1)

        made = await photo(maker, feat, a, conv_a)
        reused = await photo(maker, feat, b, conv_b)  # b gets a's picture from the cache
        assert reused.from_cache and reused.key == made.key

        await forget_chat_pictures(maker)
        again = await photo(maker, feat, b, conv_b)  # b already got it: must not get it again
        assert again.key != made.key and not again.from_cache

        async with maker() as s:
            delivered = (
                await s.execute(
                    select(ImageGeneration.user_id, ImageGeneration.source, ImageGeneration.image_key)
                    .where(ImageGeneration.delivery == "delivered")
                )
            ).all()
        assert (b, "cache", made.key) in delivered  # the ledger says who got which picture

    run_db(scenario)


def test_a_picture_that_was_not_delivered_is_not_remembered(run_db, tmp_path):
    async def scenario(maker):
        a, character_id, conv_a = await seed_conversation(maker)
        b, conv_b = await another_chat(maker, character_id, "b@example.test")
        feat = feature(tmp_path, variants=1)

        made = await photo(maker, feat, a, conv_a)
        await photo(maker, feat, b, conv_b, deliver=False)  # Telegram never delivered it to b
        again = await photo(maker, feat, b, conv_b)

        assert again.from_cache and again.key == made.key  # b has still not seen it
        assert len(feat.provider.calls) == 1

    run_db(scenario)
