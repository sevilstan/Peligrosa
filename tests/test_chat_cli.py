import pytest

from app.models import Character, User
from scripts.chat_cli import (
    find_latest_conversation,
    get_active_character,
    get_or_create_user,
    parse_args,
)
from tests.test_conversation_engine import ScriptedProvider
from app.services.conversation_service import ConversationService


def test_parse_args_defaults():
    args = parse_args(["--character", "elena"])

    assert args.character == "elena"
    assert args.provider == "groq"
    assert args.new is False


def test_parse_args_requires_a_character():
    with pytest.raises(SystemExit):
        parse_args([])


def test_local_user_is_created_once_and_reused(run_db):
    async def scenario(maker):
        async with maker() as session:
            first = await get_or_create_user(session, "cli@example.test", "tr")
            second = await get_or_create_user(session, "cli@example.test", "tr")

            assert first.id == second.id

    run_db(scenario)


def test_unknown_character_error_lists_available_slugs(run_db):
    async def scenario(maker):
        async with maker() as session:
            session.add(
                Character(
                    name="Testa", slug="testa", description="d",
                    personality="p", system_prompt="s",
                )
            )
            await session.commit()

            with pytest.raises(ValueError, match="Available: testa"):
                await get_active_character(session, "missing")

    run_db(scenario)


def test_latest_conversation_is_resumed_and_none_when_there_is_no_history(run_db):
    async def scenario(maker):
        async with maker() as session:
            user = User(email="cli@example.test", language_code="tr")
            character = Character(
                name="Testa", slug="testa", description="d",
                personality="p", system_prompt="s",
            )
            session.add_all([user, character])
            await session.commit()
            user_id, character_id = user.id, character.id

            assert await find_latest_conversation(session, user_id, character_id) is None

            service = ConversationService(session, ai_provider=ScriptedProvider())
            created = await service.create_conversation(user_id, character_id)
            created_id = created.id

            found = await find_latest_conversation(session, user_id, character_id)
            assert found.id == created_id

    run_db(scenario)
