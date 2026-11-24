# Group Orchestration — Design Proposal

Status: **proposal, no code yet.** Roadmap step 5. For the product owner's review
(and ChatGPT's architecture review) before any implementation.

Related: `CLAUDE.md` sections 7 (memory rules) and 8 (future group system).

---

## 1. Goal

In a persistent group (2-4 characters + the user) characters talk like
individuals: they answer, stay silent, react to each other, disagree, and
carry what happened into other conversations. Out of scope for this step:
characters starting conversations on their own (initiative), web UI, own models.

---

## 2. Memory decision (owner + ChatGPT): memory belongs to the character

> Memory is not tied to a group or a chat. It is kept per **user + character**.

If Elena learns something about Osman in group A, it is part of *Elena's*
memory and she can use it in group B or in a direct chat. Natalie only knows
it if she was present or was told, and then stores it in *her own* memory.

### 2.1 Audit: does the current system already support this?

Checked against the code on `main`:

| Requirement | Today |
|---|---|
| Memory scoped by (user_id, character_id), not by conversation | **Yes.** `character_memories` has no conversation column; unique keys are (user, character, memory_key) and (user, character, category, content). |
| Retrieval independent of the conversation | **Yes.** `ConversationService.build_system_prompt` loads `get_memories(user_id, character_id)`; the chat/group is irrelevant. |
| Each character stores independently | **Yes.** `add_memory` takes a character_id; the same fact can exist once per character (CLAUDE.md rule 4). |
| Characters cannot read each other's memory | **Yes.** Every query includes both ids (tests + canaries exist). |
| Memory survives chats being deleted | **Yes.** No FK to conversations. Deleting a *character* (PR #10) removes it by (user, character). |
| Learning from groups | **No.** Extraction only runs in `ConversationService.send_message`, which is direct-only, and only on the **user's** message. |
| Memory of *events* and of what happened between characters | **No.** `MemoryExtractor.ALLOWED_CATEGORIES` = interest, preference, personal, goal, hobby. |
| A character's thoughts about another character | **No** storage and no extraction. |
| Emotions that persist | **No.** |
| Choosing the *relevant* memories | **Weak.** Top 10 by importance/recency (`MEMORY_LIMIT`). Fine for facts, will not scale to events. |
| Knowing where a memory came from | **No** (no provenance). |

Conclusion: **the storage model already matches the principle; the gaps are
what we extract, how we pick memories, and provenance.** `category` is a free
`VARCHAR(50)` without a DB check, so new categories need **no migration**.

### 2.2 Rules (additions to CLAUDE.md section 7)

1. A character only remembers what it **witnessed** (messages of conversations
   it is part of) or was **told**. No character reads another's memory.
2. Group events and opinions about others are stored in the character's own
   memory, never "in the group".
3. Retrieval stays `(user_id, character_id)`; never by conversation.
4. A fact told privately in a direct chat is not visible to other characters.
   If the character says it aloud in a group, it becomes witnessed there and
   others may remember it (see open decision D1).
5. Deleting a chat or a group does not delete memories; deleting a character
   does (already implemented).

### 2.3 Worked example (the cross-group case)

1. Group A (Elena, Natalie, user): the user says Osman got a new job.
   Elena and Natalie each save an `event` memory for themselves.
2. Group B (Elena, Dee, user): Elena may bring it up. Dee has no such memory
   and learns it only if Elena says it there (then Dee stores it herself).
3. Direct chat with Elena: she remembers it too; Natalie's memory is untouched.

### 2.4 Proposed memory additions

- **New categories** in the extractor: `event` (something that happened, also
  in groups), `relationship` (a character's view of another character or of
  the user's people). Keys follow the existing scheme, e.g. `event_osman_new_job`,
  `rel_natalie`. No migration.
- **Provenance** (small migration): `character_memories.source_conversation_id`
  (nullable FK, `ON DELETE SET NULL`) and `source_kind` (`direct` / `group`).
  Used for the privacy rule (2.2 #4), debugging and future cleanup. Optional
  but recommended.
- **Relevance-aware retrieval** instead of "top 10": always include top
  importance, plus memories matching the current topic or the people present
  (keyword match first; embeddings only if needed later). Token budgeted.
- **Structured relationship and mood state** (see 5), because numbers are
  needed for behaviour, text is only for flavour.

---

## 3. Turn pipeline (user writes in a group)

All messages of one user are already handled one at a time, in order
(`ChatOrderMiddleware`).

1. **Save** the user message.
2. **Who speaks?** (3.1)
3. **Generate** each chosen speaker's reply, one after another, so a later
   speaker can react to an earlier one. Each reply is saved with
   `sender_character_id`.
4. **Optional follow-up hop**: at most one extra round where a character reacts
   to another character's message, capped (3.2).
5. **Send** the replies as separate Telegram messages (one bot, so each message
   starts with the character's name in bold; a short typing pause between them
   keeps it natural).
6. **After the turn (background, batched)**: memory extraction for every
   present character, relationship and mood updates (see 5), summary update.

Failure of any background step never blocks or removes a reply (same rule as
memory/summary today).

### 3.1 Speaker selection (cheap rules first, AI only when needed)

1. **Addressed directly** ("Elena, ..." / reply to a character's message / `@name`):
   that character speaks; no AI call needed.
2. **Question from a character to the user** (the last message was a character
   asking the user something): other characters stay out unless the user's
   answer concerns them.
3. **Otherwise** a small structured **director call** (JSON, cheap model):
   input = last ~6 messages + one line per character (personality, current mood,
   relationship to the others); output = ordered speakers (0..2) with an
   intent (`answer_user`, `react_to:<slug>`, `tease`, `stay_silent`).
   Output is validated like all model output (slugs must be members, caps
   enforced, invalid -> fall back to the most relevant single speaker).

Silence is a valid result. The director must not default to "everyone speaks".

### 3.2 Budgets and caps (configuration, not hard-coded)

- max characters speaking per user message: the **group size** (up to 4), per D2 in section 7 (earlier proposal: 2);
- max follow-up hops: **1**;
- max total character messages per user message: a configurable safety cap (proposal: 6, including the follow-up hop);
- per-turn timeout; if the budget is hit the turn ends gracefully.

### 3.3 Group context for a character's prompt

Built by a `GroupConversationContextBuilder`; per speaker it contains, in order:
identity/personality/behaviour rules (existing builder), **who is in the room**,
this character's own memories (relevance-aware), its **relationship state
towards each present member**, its **current mood**, the group summary, the
recent messages **labelled by speaker name**, and the speaker's intent from the
director. It never contains another character's memory or relationship state.

---

## 4. Calls per user message and rate limits

| Step | Calls |
|---|---|
| Speaker selection | 0 (addressed) or 1 |
| Replies | 1-3 |
| Memory extraction (one call, result fanned out to each present character) | 1 |
| Batched reflection (relationships, mood, events) | ~1 per 6-10 messages |
| Summary (existing) | ~1 per 10 messages |

About **3-6 calls per user message** in a 3-character group (today a direct
message is 2). The free Groq limit (30 requests/min on gpt-oss) allows only a
few group messages per minute across *all* users, so this is fine for testing and
**not** for a public launch. Mitigations: different models per role through the
existing provider abstraction (`GroqProvider(model=...)`): small/cheap for
director, extraction and reflection, better model for the voices; a provider-side
rate limiter/queue so users get "typing..." instead of errors; a paid tier before
real traffic.

---

## 5. Relationships and emotions (persistent, per user)

New tables (migration), both scoped by `user_id`:

- `character_relationships(user_id, character_id, other_character_id, trust,
  affection, respect, jealousy, rivalry, familiarity, tension, updated_at)` —
  **directional**: Elena->Natalie and Natalie->Elena are separate rows
  (asymmetry, per CLAUDE.md). Values 0..100, small bounded changes per update.
- `character_emotions(user_id, character_id, mood, intensity, reason,
  updated_at)` — one current state per character; decays towards neutral over
  time so a bad mood is not permanent, but does **not** reset per message.

Updated by the batched reflection call (structured JSON, validated, deltas
clamped). Text-level thoughts ("I think Natalie is show-off") go to
`character_memories` with category `relationship`. Both are loaded only for the
speaking character (3.3).

---

## 6. Suggested implementation steps (small PRs, each testable alone)

- **A. Memory foundation**: new categories + provenance + relevance-aware
  retrieval. Works and is testable on direct chats, no groups needed.
- **B. Group messaging, single speaker**: context builder, labelled history,
  persistence of character messages in groups, addressed-speaker rule,
  Telegram rendering with name prefix. Memory fan-out to present characters.
- **C. Speaker selection**: director call, validation, silence, caps.
- **D. Multi-speaker and follow-up hop** with budgets and rate limiting.
- **E. Relationships and moods**: tables, reflection call, decay.
- **F. (later)** Initiative / scheduled character-started messages.

Testing: deterministic `ScriptedProvider` (existing pattern) with a scripted
director; isolation canaries for every new query (character A must never see B);
mutation checks for caps, validation and scoping; a golden scenario test for the
Osman cross-group example.

---

## 7. Decisions

Decided by the product owner (2026-11-24):

- **D1 Privacy across rooms: depends on the character.** There is no global
  rule. Whether a character mentions in a group something told to it privately
  is part of its personality (discreet vs. gossipy), expressed in its character
  definition and prompt. Provenance (`source_kind`) is recorded so this can be
  applied and inspected.
- **D2 Speakers: natural.** No fixed number of speakers: a character speaks if
  it has something to say at that moment; groups hold up to **4** characters.
  Replaces the "2 speakers" default in 3.2: the per-turn reply cap equals the
  group size, and a total-message safety cap (including the follow-up hop)
  stays as a cost guard, configurable.
- **D3 Model choice per role:** postponed; stay on the free tier for now.
- **D4 Telegram presentation: one bot**, each message prefixed with the
  character's name.
- **D5 Relationship visibility: behaviour only.** Trust/affection and other
  values are never shown to the user; they only shape how characters act.

## 8. Progress

- **A. Memory foundation: implemented** (PR "Memory foundation"): `event` and
  `relationship` categories, provenance columns, relevance-aware recall
  (half the memory budget always goes to the most important memories, the rest
  to memories matching the recent conversation topic), same prompt size.
- **B. Group messaging, single speaker: implemented.** `GroupConversationService`
  answers a user message with ONE character chosen by cheap rules
  (`speaker_selection`: addressed by name/@, else the previous speaker, else the
  first member). Prompt = the character's own prompt + a "who is in the room"
  section; history is labelled by speaker name; the summary is labelled too.
  One memory extraction per message is stored separately for every member
  (`source_kind="group"`); deletion requests apply to every member. Telegram
  replies start with the bold character name. Director call, silence and
  multi-speaker come in C and D.
- **C. Speaker director: implemented (still one speaker per message).** When
  nobody is addressed by name, a small structured call (`SpeakerDirector`) reads
  the last 6 messages and returns a member slug or `null` (silence). Output is
  validated; any failure falls back to the rule-based choice, so a reply is never
  lost. Silence saves the user's message and sends nothing in Telegram. Cost:
  +1 call only for messages that do not address a character by name.
- **D. Multi-speaker: implemented (owner decision 2026-11-24: if nobody is
  addressed, everyone or most answer).** Addressed by name -> only that
  character. Otherwise the director returns an ordered list of speakers
  (`{"speakers": [...]}`, usually everyone, fewer when some have nothing to say,
  empty = silence); if it fails, everyone answers. Replies are generated one
  after another so later speakers see (and must not repeat) earlier ones, and
  each is sent to Telegram as soon as it is saved. Cap: `MAX_REPLIES_PER_TURN`
  (4); a failure after the first reply keeps the earlier replies. Cost in a
  4-member group: up to 1 director + 4 replies + 1 extraction per message,
  so the Groq free limit (30 RPM) allows only a handful of group messages per
  minute. The follow-up hop (characters reacting to each other without a new
  user message) is not part of this step.
- **D2. Character-to-character follow-up: implemented (owner request
  2026-11-24: sometimes one AI asks another and gets an answer, but cheaply).**
  After the normal replies, in only ~25% of turns (`FOLLOWUP_CHANCE`) a small
  check (`choose_followup`, default answer "no") may pick a sender and a target:
  the sender says something short to the target and the target answers. One
  exchange (2 messages) per user message, never a chain, inside a total cap of
  6 messages (`MAX_TOTAL_REPLIES_PER_TURN`). Any failure just means no
  follow-up. Extra cost: ~0.25 check + ~0.1 x 2 replies per turn on average.
- **E1. Relationships and moods, storage + use: implemented (nothing writes
  them from conversations yet).** Tables `character_relationships`
  (directional, 7 values 0..100) and `character_emotions` (one mood per
  character, fades 10 points/hour, computed on read), both per user, with a
  `CharacterRelationshipService` / `CharacterEmotionService` (updates are
  clamped to +-5 per step, model input untrusted). In a group, a speaker's prompt
  gets a private "YOUR FEELINGS" section built ONLY from its own rows
  (behaviour hints, never numbers). Removing a character deletes its feelings
  and everyone's feelings about it for that user. **E2 (next): the batched
  reflection call that actually updates these from what happens in the chat.**
- **E2. Feelings reflection: implemented.** In groups, every 8 new messages
  (`REFLECTION_MIN_NEW_MESSAGES`) one batched call (`RelationshipReflector`)
  reads only the new messages and returns small relationship changes and moods.
  Output is validated (members only, known moods, whole numbers, entry caps)
  and clamped again by the state services (+-5 per pair per reflection). The
  "already reflected" counter (`conversations.reflection_message_count`, new
  migration) is advanced with a compare-and-set in the same transaction as the
  feelings, so concurrent requests cannot apply a batch twice and a failure
  leaves everything unchanged. Provider errors are retried later; unusable
  output is skipped. Cost: ~1 call per 8 messages. Characters now react to
  what happened (e.g. Bob stays upset after Amy teased him) in later replies.
  Not yet: reflecting in direct chats, group events as memories, initiative (F).
- **E3. Group events as memories: implemented (the cross-group "news" case).**
  The same reflection call (no extra call) now also returns up to 3 notable
  events (`event_...` key, one factual sentence, importance 1-10). Every
  character that was in the group stores each event in ITS OWN memory
  (category `event`, `source_kind="group"`, separate records, upsert by key).
  Characters outside the group do not learn it. Because memory belongs to the
  character, the event can come up in other groups and direct chats: if Amy
  and Bob were told "Osman got a new job" in group A, Amy can mention it in
  group B, while Cy (not in A) cannot. Whether a character *does* mention it
  stays a matter of its personality (decision D1).
- **F. Initiative (characters write first): implemented, dormant by default.**
  Three switches must all be on: the operator (`INITIATIVE_ENABLED`, default
  off), the user (`/proactive on`, default off for everyone) and the rules in
  `InitiativeService`: not in quiet hours (22:00-09:00 at `INITIATIVE_UTC_OFFSET_HOURS`,
  default +3, because Telegram does not give a time zone), the active chat has
  been silent 6h-7 days, the last message is not an unanswered initiative, at
  most one initiative per user per 24h, never while the user is in a live
  conversation (shared per-user lock). Direct chat: that character writes; group:
  one random member, in its own voice with its own memories and feelings.
  Cost guard: at most `INITIATIVE_MAX_PER_CHECK` (5) messages per 15-minute
  check, and a check only costs an AI call for users who pass every rule.
  A user who blocks the bot is switched off automatically. Defaults are product
  decisions for the owner (see the PR).
