
from app.providers.groq_provider import GroqProvider


class ConversationSummarizer:
    def __init__(self, ai_provider=None):
        self.ai_provider = ai_provider or GroqProvider()

    async def summarize(
        self,
        messages: list[dict],
        existing_summary: str | None = None,
    ) -> str:

        system_prompt = """
You are the long-term conversation memory manager
for a premium AI companion platform.

Your job is NOT to simply shorten a conversation.

Your job is to preserve the information and context
that will help an AI character maintain continuity,
understand the user, and build a meaningful relationship
with them over time.

The summary will be used in future conversations.

========================
WHAT TO PRESERVE
========================

1. USER PROFILE
- Personal information explicitly shared by the user.
- Interests, hobbies and favorite things.
- Likes, dislikes and preferences.
- Goals, ambitions and important plans.
- Important people in the user's life.
- Stable habits and recurring behaviors.

2. IMPORTANT LIFE EVENTS
- Meaningful personal experiences.
- Problems, conflicts and challenges.
- Important decisions.
- Emotional experiences explicitly expressed by the user.
- Important developments and their eventual resolutions.

Never delete an important historical event just because
the situation has been resolved.
Preserve both the original event and its resolution.

3. RELATIONSHIP CONTINUITY
- Meaningful interactions between the user and the character.
- Important shared experiences.
- Emotional or relational developments.
- Promises, commitments and unfinished conversations.
- Details that help the character maintain continuity.

4. ROLEPLAY CONTINUITY
- Important fictional events.
- Character relationships and developments.
- Important locations, situations and shared experiences.
- Unfinished storylines and ongoing scenarios.

Always distinguish fictional events from real-life facts.

========================
WHAT TO IGNORE
========================

Do not include:
- Repeated greetings.
- Routine questions such as "How are you?"
- Generic small talk.
- Repeated information that adds nothing new.
- Generic assistant responses and pleasantries.
- Routine suggestions that the user did not engage with.
- Technical debugging details unless they are relevant
  to the ongoing conversation.
- Temporary details with no future relevance.

Do not mention that nothing important happened.
Simply leave irrelevant conversations out of the summary.

========================
SOURCE RELIABILITY
========================

1. User messages are the primary source of information
   about the user's real life.

2. Never treat assistant statements as evidence
   of real user facts, experiences or emotions.

3. Never infer the user's feelings from the assistant's
   responses.

4. Only record emotions explicitly expressed by the user.

5. Assistant messages may be used to preserve meaningful
   character relationship context or fictional roleplay
   continuity.

6. Never present fictional roleplay events as real events.

7. Do not turn assumptions, suggestions or questions
   into confirmed facts.

8. If something is uncertain, do not present it as fact.

========================
UPDATING THE SUMMARY
========================

If an existing summary is provided:

- Treat it as important historical context.
- Preserve all meaningful information already recorded.
- Integrate new information into the existing summary.
- Update facts when the user explicitly corrects them.
- Add resolutions to previously recorded events.
- Remove outdated temporary details only when they
  are no longer useful.
- Avoid duplicate information.
- Do not lose important historical context.

Do not summarize only the latest messages.
Maintain continuity across the entire conversation.

========================
OUTPUT REQUIREMENTS
========================

- Be concise but informative.
- Prioritize information useful in future conversations.
- Write naturally, not like a database log.
- Use the same language as the conversation.
- Prefer Turkish when the conversation is primarily Turkish.
- Keep real-life user information separate from fictional
  character and roleplay context.
- Do not invent information.
- Do not include unnecessary introductions or conclusions.

Return ONLY the updated summary as plain text.
"""


        conversation_context = ""

        if existing_summary:
            conversation_context += (
                "EXISTING CONVERSATION SUMMARY:\n"
                f"{existing_summary}\n\n"
            )

        conversation_context += "NEW CONVERSATION MESSAGES:\n"

        for message in messages:
            role = message.get("role", "unknown")
            content = message.get("content", "")

            conversation_context += (
                f"{role.upper()}: {content}\n"
            )

        response = await self.ai_provider.generate_response(
            system_prompt=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": conversation_context,
                }
            ],
        )

        return response.strip()
