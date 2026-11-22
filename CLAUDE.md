# PELIGROSA — PROJECT GUIDE & CLAUDE CODE INSTRUCTIONS

## 1. PROJECT OVERVIEW

**Project name:** Peligrosa  
**Project type:** AI Companion Platform  
**Primary language:** Python  
**Backend framework:** FastAPI  
**Database:** PostgreSQL  
**ORM:** SQLAlchemy (Async)  
**Migrations:** Alembic  
**AI providers:** Groq and OpenAI  
**Initial product interface:** Telegram Bot  
**Repository:** https://github.com/sevilstan/Peligrosa

Peligrosa is an AI companion platform designed to provide natural, persistent, emotionally rich conversations with AI characters.

The goal is not to build a conventional chatbot that simply answers questions.

We want to create AI characters that have:

- Distinct personalities.
- Long-term memories.
- Persistent emotional states.
- Individual relationships with the user.
- Relationships with other AI characters.
- Independent opinions and behavioral patterns.
- Natural social interactions.
- The ability to initiate conversations, remain silent, disagree, joke, argue, reconcile and develop over time.

The platform should feel like interacting with real personalities rather than sending messages to automated assistants.

---

## 2. PRODUCT VISION

The most important product principle:

**Every character must feel like an individual.**

For example, Elena and Natalie must not behave like two interchangeable AI assistants.

Elena should have her own personality, memories, opinions, emotions and relationship with the user.

Natalie should have a different personality, memories, opinions, emotions and relationship with the user.

They must be capable of developing independently.

### Individual character identity

Each character should have:

- A unique personality.
- A unique system prompt.
- Individual long-term memories.
- Individual emotional state.
- Individual relationship data with the user.
- Individual relationship data with other characters.

### Long-term vision

A user should eventually be able to interact with multiple AI characters in the same environment.

Characters should be able to interact with each other naturally, without behaving like a scripted group of assistants.

We should prioritize naturalness, consistency and believable personalities over simply generating more messages.

---

## 3. PRODUCT ROADMAP

The development strategy is divided into phases.

### Phase 1 — Telegram MVP

This is the current primary product priority.

We want to launch a working Telegram-based AI companion product as soon as possible.

Priorities:

1. Telegram bot integration.
2. User registration and identification.
3. Character selection.
4. Direct conversations with characters.
5. Persistent conversation history.
6. Character-specific long-term memory.
7. Conversation summaries.
8. Stable AI provider integration.
9. Reliable database operations.
10. Basic error handling and logging.
11. Production deployment.
12. Initial marketing and user acquisition.

We should not spend unnecessary time building a sophisticated web interface before the Telegram product is usable.

### Phase 2 — Web Platform

After launching the Telegram product and validating user interest, we will develop a web interface.

Potential features:

- User accounts.
- Character discovery.
- Character profiles.
- Conversation interface.
- User settings.
- Subscription and payment system.
- Character management.
- Group conversations.

### Phase 3 — Advanced AI and Own Models

Long-term goals:

- Fine-tuning our own models.
- Evaluating different language models.
- Improving personality consistency.
- Reducing inference costs.
- Optimizing latency.
- Building more advanced character behavior systems.

Do not prioritize model training during the current MVP development phase.

---

## 4. CURRENT TECHNICAL ARCHITECTURE

The project currently uses a modular Python backend.

### Main technologies

- Python 3.14
- FastAPI
- PostgreSQL 19
- SQLAlchemy Async
- asyncpg
- Alembic
- Pydantic Settings
- python-dotenv
- Groq API
- OpenAI API

### Project structure

The current project structure includes:

```text
Peligrosa/
│
├── app/
│   ├── main.py
│   │
│   ├── core/
│   │   └── config.py
│   │
│   ├── database/
│   │   ├── session.py
│   │   └── test_*.py
│   │
│   ├── models/
│   │   ├── base.py
│   │   ├── user.py
│   │   ├── character.py
│   │   ├── conversation.py
│   │   ├── conversation_participant.py
│   │   ├── message.py
│   │   ├── character_memory.py
│   │   └── user_memory.py
│   │
│   ├── providers/
│   │   ├── base.py
│   │   ├── groq_provider.py
│   │   └── openai_provider.py
│   │
│   └── services/
│       ├── character_memory_service.py
│       ├── conversation_service.py
│       ├── conversation_service_backup.py
│       ├── conversation_summarizer.py
│       ├── memory_extractor.py
│       └── memory_service.py
│
├── migrations/
│   └── versions/
│
├── alembic.ini
├── .env
├── .env.example
└── .gitignore
```

This structure is a snapshot of the project, not an immutable specification. Always inspect the actual repository before making assumptions.

---

## 5. COMPLETED DEVELOPMENT

The following functionality has already been implemented.

### 5.1 Database infrastructure

- PostgreSQL database configured.
- Async SQLAlchemy session infrastructure implemented.
- Database models created.
- Alembic migration infrastructure configured.
- Database schema managed through migrations.

### 5.2 User model

A user model exists to represent platform users.

Conversations and memories must be scoped to the correct user.

### 5.3 Character model

The character model includes:

- Name.
- Slug.
- Description.
- Personality.
- System prompt.
- Avatar URL.
- Active status.
- Sort order.
- Creation timestamp.

Personality and system prompt are separate fields.

This distinction is important because personality information and operational instructions should not be mixed unnecessarily.

### 5.4 Conversation system

Conversation infrastructure supports:

- Users.
- Conversations.
- Messages.
- Conversation participants.
- Direct and group conversation types.

The conversation model includes:

- Conversation type.
- Summary.
- Summary message count.
- Participants.
- Messages.

The participant model uses:

- conversation_id
- character_id

as a composite primary key.

The existing database structure is already capable of representing multiple characters in a conversation.

However, the current ConversationService still enforces one character per conversation when sending messages.

Do not confuse database-level group support with a fully implemented group conversation engine.

### 5.5 Message system

Messages distinguish between:

- User messages.
- Character messages.

User messages reference sender_user_id.

Character messages reference sender_character_id.

The database enforces the sender relationship through a check constraint.

### 5.6 AI provider architecture

Provider abstraction has been implemented.

Current providers:

- GroqProvider
- OpenAIProvider

The application should remain flexible enough to support additional providers.

Avoid tightly coupling business logic to one specific AI provider.

### 5.7 Conversation summarization

A ConversationSummarizer service exists.

Its purpose is to maintain a compact summary of older conversation history.

Current behavior:

- Tracks summary_message_count.
- Detects new messages.
- Starts summarization after at least 10 new messages.
- Updates the conversation summary.
- Uses the summary as context for future AI responses.

The purpose is to preserve continuity without sending the entire conversation history on every request.

### 5.8 Character-specific long-term memory

This is one of the most important completed components.

The CharacterMemory system stores memories separately for each user and character.

The memory ownership principle is:

**A character must only access its own memories belonging to the current user.**

The logical memory scope is:

(user_id, character_id)

Examples:

- Elena remembers that the user likes science fiction.
- Natalie does not automatically access Elena's private memory.
- Another user must never access this user's memories.
- Elena's memory must not leak into another user's Elena conversation.

The CharacterMemory model includes:

- user_id
- character_id
- category
- content
- importance
- confidence
- memory_key
- timestamps

Memory keys provide stable identifiers for memories.

Examples:

- favorite_movie
- interest_science_fiction
- preferred_music
- personal_goal

A unique constraint exists for user_id, character_id and memory_key.

Legacy records are also supported through nullable memory_key.

### 5.9 CharacterMemoryService

The service currently supports:

- Adding memories.
- Updating existing memories.
- Searching by memory key.
- Avoiding duplicate records.
- Retrieving memories.
- Deleting memories by ID.
- Deleting memories by key.
- Enforcing user and character ownership.

A legacy fallback exists to avoid creating duplicate memories when older records do not have memory_key.

Do not remove this compatibility logic without understanding the database constraints.

### 5.10 MemoryExtractor

MemoryExtractor extracts potentially useful long-term information from user messages.

Supported categories:

- interest
- preference
- personal
- goal
- hobby

Supported operations:

- upsert
- delete

The extractor uses structured output and validates the returned information.

Explicit deletion requests are treated carefully.

Examples:

- "Bunu hafızandan sil." → deletion request.
- "Bunu hafızandan silme." → not a deletion request.
- "Forget my favorite movie." → deletion request.
- "Don't delete that memory." → not a deletion request.
- "Interstellar artık favorim değil." → not automatically a deletion request.

Deletion operations require sufficient confidence and explicit user intent.

Do not weaken these safeguards.

### 5.11 Conversation memory integration

ConversationService currently:

1. Loads the conversation.
2. Validates ownership.
3. Validates that it is a direct conversation.
4. Saves the user message.
5. Runs memory extraction.
6. Updates or deletes character-specific memories.
7. Loads conversation history.
8. Retrieves the character's memories.
9. Adds memory context to the system prompt.
10. Adds the conversation summary.
11. Calls the selected AI provider.
12. Saves the character response.
13. Updates the conversation summary.

This pipeline has been tested with a FakeAIProvider.

---

## 6. TESTING STATUS

The following tests have previously passed:

### Character memory tests

9/9 tests passed.

Covered:

- Creating memories.
- Updating memories using the same key.
- Preventing duplicates.
- Character isolation.
- User isolation.
- Preventing unauthorized deletion.
- Deleting by memory key.
- Ensuring deleted records are not visible.

### Conversation memory integration

Passed.

Verified:

- Extracting user preferences.
- Saving memories to Elena.
- Retrieving memories.
- Including memories in the AI prompt.

### Memory extractor tests

Deletion intent tests passed for the listed Turkish and English examples.

### Important testing principle

A previously passing test does not mean the current code still passes.

Always inspect the current code and run relevant tests after modifying related components.

Do not claim that tests passed unless you actually executed them.

---

## 7. IMPORTANT MEMORY AND PRIVACY RULES

These rules are architectural requirements.

### Rule 1 — Character isolation

Every character has its own memory space.

Never retrieve memories using only user_id.

Always include character_id when retrieving character memories.

### Rule 2 — User isolation

One user's memories must never be visible to another user.

### Rule 3 — Direct conversations and group conversations

A character may use its own memories in both direct and group conversations.

However, a character must not read another character's private memories.

### Rule 4 — Group conversation memory

If a user shares a general fact in a group conversation, each participating character may independently remember that fact in its own memory space.

For example:

The user says:

"I love science fiction."

Elena may save this in Elena's memory.

Natalie may independently save the same information in Natalie's memory.

These remain separate records.

### Rule 5 — Conversation history

Characters can see messages that are part of their shared conversation.

This does not grant access to another character's private direct conversation history or private memory records.

### Rule 6 — Memory deletion

Respect explicit deletion requests.

Do not delete information merely because the user expresses a change of opinion.

---

## 8. FUTURE GROUP CONVERSATION SYSTEM

This is a major future feature.

The existing database already supports multiple conversation participants, but the conversation orchestration layer needs to be developed.

The goal is to create natural social interactions between multiple AI characters.

### Example scenario

A group contains:

- User
- Elena
- Natalie

The user says:

"I really love science fiction movies."

Elena might respond:

"I knew you'd say that. Interstellar is still your favorite, right?"

Natalie might respond:

"Science fiction is great, but I think psychological thrillers are better."

Both responses can be natural.

However, characters must not respond to every message automatically.

### Speaker selection

If Elena asks the user:

"How was your day?"

Natalie should not automatically answer on the user's behalf.

If the user shares a general opinion, both characters may decide to participate.

The system should determine:

- Who should respond?
- Should multiple characters respond?
- Should a character remain silent?
- Should a character initiate a side conversation?
- Should a character react emotionally?
- Should a character respond to another character instead of the user?

### Character-to-character interaction

Characters should be able to:

- Ask each other questions.
- Reply to each other.
- Disagree.
- Make jokes.
- Tease each other.
- Argue.
- Get jealous.
- Become upset.
- Apologize.
- Reconcile.
- Develop friendships or rivalries.

### Persistent relationships

Relationships should be independent and potentially asymmetric.

For example:

Elena may trust Natalie.

Natalie may dislike Elena.

These are not contradictory. They represent separate perspectives.

Potential relationship attributes:

- Trust.
- Affection.
- Respect.
- Jealousy.
- Rivalry.
- Familiarity.
- Tension.

Relationships should evolve through conversation history and meaningful events.

### Persistent emotions

Emotions should not reset on every message.

For example:

Elena gets upset with Natalie.

The next message should not automatically make Elena happy again.

Her emotional state should influence future responses until something changes it.

### Proposed architecture

Potential components:

- GroupConversationOrchestrator
- SpeakerSelectionService
- CharacterRelationshipService
- CharacterEmotionService
- GroupConversationContextBuilder

These are architectural proposals, not existing implemented modules.

Before implementation, inspect the current code and propose a design that fits the existing architecture.

### Performance

We want natural group conversations without unnecessary AI calls.

Avoid generating multiple full responses simply to decide who speaks.

Consider efficient speaker selection, structured outputs and controlled response generation.

Correctness and natural behavior are more important than blindly minimizing API calls.

---

## 9. CLAUDE CODE RESPONSIBILITIES

Claude Code is a development partner.

It should actively help with:

1. Inspecting the codebase.
2. Understanding the existing architecture.
3. Identifying bugs and architectural weaknesses.
4. Implementing requested features.
5. Writing and improving tests.
6. Refactoring when justified.
7. Reviewing database relationships.
8. Reviewing migrations.
9. Improving error handling.
10. Improving performance.
11. Reviewing security and privacy.
12. Maintaining technical documentation.

Claude should not independently change the product roadmap.

The user is the product owner and makes final decisions.

### Expected behavior

Before implementing a feature:

1. Inspect the relevant files.
2. Understand existing dependencies.
3. Identify affected database models and services.
4. Explain the proposed implementation.
5. Identify possible breaking changes.
6. Ask for clarification if a product decision is genuinely necessary.

For small, clearly specified changes, Claude may proceed without unnecessary approval requests.

After implementation:

1. Explain what changed.
2. List modified and newly created files.
3. Explain important design decisions.
4. Run relevant tests.
5. Report actual test results.
6. Mention unresolved issues.
7. Provide the exact Git commands needed to review and commit the changes.

Never claim that a feature is complete if only part of it was implemented.

---

## 10. COLLABORATION BETWEEN CHATGPT AND CLAUDE

The project will be developed collaboratively using ChatGPT and Claude Code.

### ChatGPT responsibilities

ChatGPT will primarily help with:

- Product architecture.
- Technical planning.
- Feature requirements.
- System design.
- Database design reviews.
- Security and privacy reviews.
- Code reviews.
- Test strategy.
- Debugging.
- Evaluating Claude's implementation.
- Keeping the development direction consistent.

### Claude Code responsibilities

Claude Code will primarily help with:

- Reading the local repository.
- Inspecting multiple files.
- Editing code.
- Implementing features.
- Running tests.
- Debugging local errors.
- Reviewing local Git changes.
- Maintaining documentation.

### Shared source of truth

The Git repository is the shared source of truth.

Claude's local changes are not automatically visible to ChatGPT.

When Claude makes changes:

1. Inspect the changes with Git.
2. Review the diff.
3. Run relevant tests.
4. Commit and push approved changes.
5. ChatGPT can then inspect the updated repository through its GitHub integration.

Do not assume ChatGPT can see uncommitted local changes.

Do not assume Claude can see uncommitted changes made in another environment.

Always synchronize through Git or explicitly share the relevant code and diff.

---

## 11. DEVELOPMENT WORKFLOW

We prefer small, controlled development steps.

Do not implement ten unrelated features at once.

The preferred workflow:

### Step 1 — Understand

Inspect the relevant files and understand the current implementation.

### Step 2 — Plan

Explain:

- What needs to change.
- Which files will be affected.
- Whether database changes are necessary.
- What could break.
- How the change will be tested.

### Step 3 — Implement

Make focused changes.

Avoid unrelated refactoring.

Preserve existing behavior unless the task explicitly requires changing it.

### Step 4 — Test

Run relevant tests.

Use fake providers for tests that should not consume real API credits.

Never expose API keys in logs or test output.

### Step 5 — Review

Inspect:

```bash
git status
git diff --stat
git diff
```

Look for:

- Accidental file changes.
- Secrets.
- Unnecessary dependencies.
- Broken imports.
- Database compatibility problems.
- Missing tests.

### Step 6 — Report

Provide a concise but technically useful summary.

Include:

- What was implemented.
- Which files changed.
- Tests executed.
- Test results.
- Remaining risks.
- Suggested next step.

### Step 7 — Git

Do not automatically commit or push without the user's approval.

The user should review changes before they become part of the shared main branch.

---

## 12. CODING PRINCIPLES

Follow these principles throughout development.

### Architecture

- Keep business logic out of API route handlers.
- Use services for business operations.
- Keep database models focused on persistence.
- Keep provider-specific logic inside provider implementations.
- Prefer modular, reusable components.
- Avoid unnecessary abstraction.

### Database

- Use asynchronous database operations consistently.
- Use SQLAlchemy patterns already established in the project.
- Create Alembic migrations for schema changes.
- Never modify production schema manually.
- Consider existing data before changing constraints.
- Avoid destructive migrations unless explicitly approved.

### Security

- Never hardcode API keys.
- Never commit `.env`.
- Never print secrets in logs.
- Validate conversation ownership.
- Enforce user and character memory isolation.
- Do not trust user input or model output without validation.
- Treat AI-generated structured output as untrusted input.

### AI integration

- Keep provider implementations independent.
- Avoid hardcoding model-specific behavior into business services.
- Handle timeouts and provider errors.
- Use structured outputs when appropriate.
- Keep prompts maintainable.
- Optimize token usage without sacrificing conversation quality.

### Code quality

- Prefer readable code over clever code.
- Avoid unnecessary complexity.
- Do not create duplicate services.
- Do not silently change public interfaces.
- Do not remove working functionality without a reason.
- Add tests for important business rules.

---

## 13. IMPORTANT PROJECT CONSTRAINTS

1. Telegram MVP is the current priority.
2. Do not prioritize the web interface yet.
3. Do not start training our own model yet.
4. Do not redesign the entire backend without a clear reason.
5. Do not assume group conversations are already implemented.
6. Do not weaken character memory isolation.
7. Do not remove existing UserMemory functionality without understanding its purpose.
8. Do not modify migrations casually.
9. Do not expose secrets.
10. Do not push changes without user approval.
11. Do not invent test results.
12. Do not make major product decisions independently.

---

## 14. FIRST TASK FOR CLAUDE CODE

When first opening this project, do not immediately modify files.

First perform a repository review.

Inspect:

- Current project structure.
- Existing database models.
- Existing services.
- Provider implementations.
- Alembic migration history.
- Existing tests.
- Current Git status.
- Existing dependencies.
- Telegram integration status.

Then prepare a report containing:

1. What currently exists.
2. What is working.
3. What is incomplete.
4. What is missing.
5. Any architectural problems.
6. Any security concerns.
7. Any inconsistencies between models and migrations.
8. Recommended next development step.

Do not implement anything during this initial audit.

Wait for the user's approval before starting the next development task.

---

## 15. FINAL DEVELOPMENT PHILOSOPHY

Peligrosa should not become a collection of disconnected chatbot features.

We are building a coherent AI companion platform.

Every technical decision should support the long-term product vision:

- Persistent identities.
- Individual personalities.
- Reliable long-term memory.
- Emotional continuity.
- Natural social interactions.
- Character-to-character relationships.
- Scalable architecture.
- Sustainable operating costs.

Think about the long-term architecture, but implement in small, testable steps.

**The goal is not simply to make AI characters talk. The goal is to make users feel that they are interacting with distinct personalities who remember, react, develop and have relationships of their own.**