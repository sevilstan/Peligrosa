import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.services.character_memory_service import CharacterMemoryService
from app.services.memory_extractor import MemoryExtractor
from app.models.message import Message
from app.models.user import User
from app.models.character import Character
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.services.conversation_summarizer import ConversationSummarizer
from app.services.character_prompt_builder import CharacterPromptBuilder
from app.services.character_definition_loader import CharacterDefinitionLoader
from app.providers.groq_provider import GroqProvider

logger = logging.getLogger(__name__)

# Summarize only once this many unsummarized messages have piled up.
SUMMARY_MIN_NEW_MESSAGES = 10
# How many of the latest unsummarized messages are sent to the model.
RECENT_MESSAGE_LIMIT = 20
# How many of the character's memories about the user go into the prompt.
MEMORY_LIMIT = 10


class AIResponseError(Exception):
    """The AI provider could not produce a reply.

    The user's message is already saved when this is raised, so a caller
    (for example the Telegram handler) can tell the user to try again.
    """


class ConversationService:
    def __init__(self, session: AsyncSession, ai_provider=None):
        self.session = session
        self.ai_provider = ai_provider or GroqProvider()
        self.summarizer = ConversationSummarizer(ai_provider=self.ai_provider)
        self.memory_extractor = MemoryExtractor(ai_provider=self.ai_provider)
        self.prompt_builder = CharacterPromptBuilder()
        self.character_definition_loader = CharacterDefinitionLoader()

    async def create_conversation(
        self,
        user_id,
        character_id,
        title=None,
    ):
        user_result = await self.session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

        if user is None:
            raise ValueError("Kullanıcı bulunamadı.")

        character_result = await self.session.execute(
            select(Character).where(
                Character.id == character_id,
                Character.is_active.is_(True),
            )
        )
        character = character_result.scalar_one_or_none()

        if character is None:
            raise ValueError("Karakter bulunamadı veya aktif değil.")

        conversation = Conversation(
            user=user,
            title=title or character.name,
            conversation_type="direct",
        )

        conversation.participants.append(ConversationParticipant(character=character))

        self.session.add(conversation)
        await self.session.commit()

        return conversation

    async def update_conversation_summary(
        self,
        conversation: Conversation,
        speaker_names: dict | None = None,
    ):
        """Summarize older messages once enough new ones have piled up.

        Safe to call concurrently for the same conversation: the result is
        written with a compare-and-set on summary_message_count, so only one
        writer wins and the others discard their (duplicate) summary. No row
        lock is held during the AI call, so new messages are never blocked.
        """
        previous_count = conversation.summary_message_count

        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        )

        messages = result.scalars().all()
        new_messages = messages[previous_count:]

        logger.debug(
            "Summary check: total=%d already_summarized=%d new=%d",
            len(messages),
            previous_count,
            len(new_messages),
        )

        if len(new_messages) < SUMMARY_MIN_NEW_MESSAGES:
            return

        summarizer_messages = [
            {
                "role": "user" if message.sender_type == "user" else "assistant",
                "content": self._summary_line(message, speaker_names),
            }
            for message in new_messages
        ]

        updated_summary = await self.summarizer.summarize(
            messages=summarizer_messages,
            existing_summary=conversation.summary,
        )

        update_result = await self.session.execute(
            update(Conversation)
            .where(
                Conversation.id == conversation.id,
                Conversation.summary_message_count == previous_count,
            )
            .values(
                summary=updated_summary,
                summary_message_count=len(messages),
                # Keep updated_at as is: it marks the chat the user last
                # opened, and a late background summary must not change it.
                updated_at=Conversation.updated_at,
            )
            .execution_options(synchronize_session=False)
        )

        await self.session.commit()

        if update_result.rowcount == 0:
            logger.info("Summary was already updated by another request; skipping.")
            await self.session.refresh(conversation)
            return

        # Already written by the UPDATE above. set_committed_value refreshes
        # the in-memory object without marking it changed; a plain assignment
        # would make the next flush UPDATE the row again (bumping updated_at).
        set_committed_value(conversation, "summary", updated_summary)
        set_committed_value(conversation, "summary_message_count", len(messages))
        logger.info("Conversation summary updated (%d messages).", len(messages))

    @staticmethod
    def _summary_line(message, speaker_names: dict | None) -> str:
        """In a group, say WHO spoke: several characters share one "assistant"
        role, and a summary that mixes them up would give one character
        another's words."""
        if speaker_names is None or message.sender_type == "user":
            return message.content

        name = speaker_names.get(message.sender_character_id, "Someone")
        return f"{name}: {message.content}"

    async def send_message(
        self,
        conversation_id,
        user_id,
        content,
    ):
        conversation, character = await self._load_direct_conversation(
            conversation_id, user_id
        )

        content = content.strip()

        if not content:
            raise ValueError("Mesaj boş olamaz.")

        # Save the user's message first: it must survive any later failure.
        self.session.add(
            Message(
                conversation_id=conversation.id,
                sender_type="user",
                sender_user_id=user_id,
                content=content,
                message_type="text",
            )
        )
        await self.session.commit()

        memories_ok = await self.update_memories(
            user_id, [character], content, conversation_id=conversation_id
        )

        if not memories_ok:
            # The rollback inside update_memories expired our ORM objects.
            conversation, character = await self._load_direct_conversation(
                conversation_id, user_id
            )

        history_result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        )
        history = history_result.scalars().all()

        unsummarized = history[conversation.summary_message_count :]

        ai_messages = [
            {
                "role": "user" if message.sender_type == "user" else "assistant",
                "content": message.content,
            }
            for message in unsummarized[-RECENT_MESSAGE_LIMIT:]
        ]

        # What is being talked about decides which memories are recalled.
        recent_user_text = " ".join(
            m["content"] for m in ai_messages if m["role"] == "user"
        )

        system_prompt = await self.build_system_prompt(
            conversation=conversation,
            character=character,
            user_id=user_id,
            context_text=recent_user_text[-1500:],
        )

        reply = await self.generate_reply(system_prompt, ai_messages)

        character_message = Message(
            conversation_id=conversation.id,
            sender_type="character",
            sender_character_id=character.id,
            content=reply,
            message_type="text",
        )

        self.session.add(character_message)
        await self.session.commit()

        # The summary is a background nicety: if it fails the user must
        # still get the reply that was just generated.
        try:
            await self.update_conversation_summary(conversation)
        except Exception as exc:
            logger.warning(
                "Summary update failed, will retry on a later message: %s",
                type(exc).__name__,
            )
            await self.session.rollback()
            # rollback expired the returned object; make it usable again.
            await self.session.refresh(character_message)

        return character_message

    async def build_system_prompt(
        self,
        conversation: Conversation,
        character: Character,
        user_id,
        context_text: str | None = None,
    ) -> str:
        """Build the system prompt the character would use right now.

        Memories are always loaded with user_id AND character_id so a
        character never sees another character's (or user's) memories.
        context_text (what is being talked about) lets relevant memories in
        beyond the most important ones; without it the top memories are used.
        """
        memories = await CharacterMemoryService(self.session).get_relevant_memories(
            user_id=user_id,
            character_id=character.id,
            context_text=context_text,
            limit=MEMORY_LIMIT,
        )

        # Prefer the platform-managed YAML definition when it exists.
        # Characters without a YAML file keep using their database fields.
        prompt_character = self.character_definition_loader.load(character.slug)
        if prompt_character is None:
            prompt_character = character

        # Only a name the user typed themselves is used: Telegram's own name is
        # often a nickname, and it should not reach the AI provider by default.
        name_row = (
            await self.session.execute(
                select(User.display_name, User.name_status).where(User.id == user_id)
            )
        ).first()
        user_name = name_row.display_name if name_row and name_row.name_status == "custom" else None

        return self.prompt_builder.build(
            character=prompt_character,
            memories=memories,
            summary=conversation.summary,
            user_name=user_name,
        )

    async def get_conversation_history(
        self,
        conversation_id,
        user_id,
    ):
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )

        conversation = result.scalar_one_or_none()

        if conversation is None:
            raise ValueError("Konuşma bulunamadı.")

        messages_result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )

        return messages_result.scalars().all()

    async def get_direct_conversation(self, conversation_id, user_id):
        """The user's own direct chat and its character, or ValueError."""
        return await self._load_direct_conversation(conversation_id, user_id)

    async def _load_direct_conversation(self, conversation_id, user_id):
        result = await self.session.execute(
            select(Conversation)
            .options(
                selectinload(Conversation.participants).selectinload(
                    ConversationParticipant.character
                )
            )
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )

        conversation = result.scalar_one_or_none()

        if conversation is None:
            raise ValueError("Konuşma bulunamadı.")

        # Direct chat only for now: exactly one character.
        if len(conversation.participants) != 1:
            raise ValueError("Doğrudan sohbet için tam olarak bir karakter gerekli.")

        return conversation, conversation.participants[0].character

    async def update_memories(
        self,
        user_id,
        characters,
        content,
        conversation_id=None,
        source_kind="direct",
    ) -> bool:
        """Extract memories from the user message ONCE and store them for
        every given character, each in its own memory space.

        A direct chat passes one character; a group passes all its members,
        so each of them independently remembers what the user said in front
        of them (same facts, separate records). A deletion request applies to
        all of them for the same reason.

        Memory is secondary to the conversation, so a failure here is logged
        and swallowed. Returns False if the session had to be rolled back.
        Only the error type is logged: database errors can carry the memory
        text as a statement parameter.
        """
        try:
            extracted_memories = await self.memory_extractor.extract(content)
        except Exception as exc:
            logger.warning("Memory extraction failed: %s", type(exc).__name__)
            return True

        if not extracted_memories:
            return True

        memory_service = CharacterMemoryService(self.session)
        character_ids = [character.id for character in characters]

        try:
            for memory in extracted_memories:
                operation = memory["operation"]
                memory_key = memory["memory_key"]

                for character_id in character_ids:
                    if operation == "delete":
                        deleted = await memory_service.delete_memory_by_key(
                            user_id=user_id,
                            character_id=character_id,
                            memory_key=memory_key,
                        )

                        if deleted:
                            logger.info("Memory deleted: %s", memory_key)

                    elif operation == "upsert":
                        await memory_service.add_memory(
                            user_id=user_id,
                            character_id=character_id,
                            category=memory["category"],
                            content=memory["content"],
                            importance=memory["importance"],
                            confidence=memory["confidence"],
                            memory_key=memory_key,
                            source_conversation_id=conversation_id,
                            source_kind=source_kind,
                        )

                        logger.info("Memory saved or updated: %s", memory_key)

            await self.session.commit()
            return True

        except Exception as exc:
            logger.warning(
                "Memory update failed, continuing without it: %s",
                type(exc).__name__,
            )
            await self.session.rollback()
            return False

    async def generate_reply(self, system_prompt, ai_messages) -> str:
        try:
            reply = await self.ai_provider.generate_response(
                system_prompt=system_prompt,
                messages=ai_messages,
            )
        except Exception as exc:
            logger.error(
                "AI provider call failed: %s", type(exc).__name__, exc_info=True
            )
            raise AIResponseError("AI provider could not generate a reply.") from exc

        reply = (reply or "").strip()

        if not reply:
            logger.error("AI provider returned an empty reply.")
            raise AIResponseError("AI provider returned an empty reply.")

        return reply
