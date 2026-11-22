"""Chat with a character from the terminal, no Telegram needed.

Run from the project root:
    python -m scripts.chat_cli --character elena
    python -m scripts.chat_cli --character elena --new
    python -m scripts.chat_cli --character elena --provider openai
    python -m scripts.chat_cli --character elena --model llama-3.3-70b-versatile

This uses the real conversation pipeline (YAML personality, long-term
memory, summaries) against the database in DATABASE_URL and calls the real
AI provider, so it saves data and uses API credits. Point DATABASE_URL at your
development database.

Commands inside the chat:
    /memory   what the character remembers about you
    /prompt   the exact system prompt the character is using right now
    /history  the last messages of this conversation
    /exit     leave (Ctrl+C / Ctrl+D also work)
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.logging_config import setup_logging
from app.database.session import SessionLocal
from app.models.character import Character
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.models.user import User
from app.services.character_memory_service import CharacterMemoryService
from app.services.conversation_service import AIResponseError, ConversationService

# One fixed local user, so memories and history persist between runs.
DEFAULT_USER_EMAIL = "local-cli@peligrosa.local"

HISTORY_SHOWN = 10


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chat with a Peligrosa character.")
    parser.add_argument("--character", required=True, help="character slug, e.g. elena")
    parser.add_argument(
        "--provider", choices=["groq", "openai"], default="groq", help="AI provider"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="model ID to use instead of GROQ_MODEL / OPENAI_MODEL from .env",
    )
    parser.add_argument(
        "--new", action="store_true", help="start a new conversation instead of resuming"
    )
    parser.add_argument("--user-email", default=DEFAULT_USER_EMAIL, help="local test user")
    parser.add_argument("--language", default="tr", help="user's language code")
    return parser.parse_args(argv)


def create_provider(name: str, model: str | None = None):
    if name == "openai":
        from app.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(model=model)

    from app.providers.groq_provider import GroqProvider

    return GroqProvider(model=model)


async def get_or_create_user(session, email: str, language: str) -> User:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=email, display_name="Local CLI user", language_code=language)
        session.add(user)
        await session.commit()

    return user


async def get_active_character(session, slug: str) -> Character:
    result = await session.execute(
        select(Character).where(Character.slug == slug, Character.is_active.is_(True))
    )
    character = result.scalar_one_or_none()

    if character is None:
        slugs = (
            await session.execute(
                select(Character.slug)
                .where(Character.is_active.is_(True))
                .order_by(Character.sort_order, Character.slug)
            )
        ).scalars().all()
        raise ValueError(
            f"No active character with slug '{slug}'. Available: {', '.join(slugs) or 'none'}"
        )

    return character


async def find_latest_conversation(session, user_id, character_id):
    result = await session.execute(
        select(Conversation)
        .join(
            ConversationParticipant,
            ConversationParticipant.conversation_id == Conversation.id,
        )
        .where(
            Conversation.user_id == user_id,
            Conversation.conversation_type == "direct",
            ConversationParticipant.character_id == character_id,
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def show_memories(session, user_id, character_id, character_name):
    memories = await CharacterMemoryService(session).get_memories(
        user_id=user_id, character_id=character_id, limit=50
    )

    if not memories:
        print(f"({character_name} henüz senin hakkında bir şey hatırlamıyor.)")
        return

    for memory in memories:
        print(f"- [{memory.category}] {memory.content}  (key: {memory.memory_key})")


async def show_prompt(service, session, conversation_id, character_id, user_id):
    conversation = await session.get(Conversation, conversation_id)
    character = await session.get(Character, character_id)
    print(
        await service.build_system_prompt(
            conversation=conversation, character=character, user_id=user_id
        )
    )


async def show_history(service, character_name, conversation_id, user_id):
    messages = await service.get_conversation_history(conversation_id, user_id)

    for message in messages[-HISTORY_SHOWN:]:
        speaker = "Sen" if message.sender_type == "user" else character_name
        print(f"{speaker}: {message.content}")


async def run_chat(args: argparse.Namespace) -> int:
    if SessionLocal is None:
        print("DATABASE_URL is not set. Check your .env file.", file=sys.stderr)
        return 1

    try:
        provider = create_provider(args.provider, args.model)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    async with SessionLocal() as session:
        try:
            user = await get_or_create_user(session, args.user_email, args.language)
            character = await get_active_character(session, args.character)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1

        # Plain values: a rolled-back session expires ORM objects.
        user_id = user.id
        character_id = character.id
        character_name = character.name

        service = ConversationService(session, ai_provider=provider)

        conversation = None if args.new else await find_latest_conversation(
            session, user_id, character_id
        )

        if conversation is None:
            conversation = await service.create_conversation(user_id, character_id)
            print(f"Yeni sohbet başladı: {character_name}")
        else:
            print(f"Sohbet devam ediyor: {character_name}")

        conversation_id = conversation.id
        # Fakes used in tests have no .model; real providers always do.
        model_name = getattr(provider, "model", "?")
        print(f"Model: {args.provider} / {model_name}")
        print("Komutlar: /memory /prompt /history /exit\n")

        while True:
            try:
                text = (await asyncio.to_thread(input, "Sen: ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not text:
                continue

            if text == "/exit":
                break
            if text == "/memory":
                await show_memories(session, user_id, character_id, character_name)
                continue
            if text == "/prompt":
                await show_prompt(service, session, conversation_id, character_id, user_id)
                continue
            if text == "/history":
                await show_history(service, character_name, conversation_id, user_id)
                continue

            try:
                reply = await service.send_message(conversation_id, user_id, text)
            except AIResponseError:
                print(f"({character_name} şu an cevap veremedi, tekrar dene.)")
                continue

            print(f"{character_name}: {reply.content}\n")

    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    setup_logging()
    return asyncio.run(run_chat(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
