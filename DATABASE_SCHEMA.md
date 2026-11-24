# Peligrosa - PostgreSQL Database Schema

- Database: `peligrosa_dev`
- Schema: `public`

## Tables


### `alembic_version`

| Column | Type | Nullable | Default |
|---|---|---|---|
| `version_num` | `VARCHAR(32)` | False | `None` |

**Primary Key:** `['version_num']`



### `users`

| Column | Type | Nullable | Default |
|---|---|---|---|
| `id` | `UUID` | False | `None` |
| `telegram_id` | `BIGINT` | True | `None` |
| `email` | `VARCHAR(255)` | True | `None` |
| `password_hash` | `VARCHAR(255)` | True | `None` |
| `display_name` | `VARCHAR(100)` | True | `None` |
| `language_code` | `VARCHAR(5)` | False | `None` |
| `is_active` | `BOOLEAN` | False | `None` |
| `created_at` | `TIMESTAMP` | False | `now()` |

**Primary Key:** `['id']`

**Unique:** `['email']`

**Unique:** `['telegram_id']`

**Index:** `users_email_key` - `['email']`

**Index:** `users_telegram_id_key` - `['telegram_id']`



### `characters`

| Column | Type | Nullable | Default |
|---|---|---|---|
| `id` | `UUID` | False | `None` |
| `name` | `VARCHAR(100)` | False | `None` |
| `slug` | `VARCHAR(100)` | False | `None` |
| `description` | `TEXT` | False | `None` |
| `personality` | `TEXT` | False | `None` |
| `system_prompt` | `TEXT` | False | `None` |
| `avatar_url` | `VARCHAR(500)` | True | `None` |
| `is_active` | `BOOLEAN` | False | `None` |
| `sort_order` | `INTEGER` | False | `None` |
| `created_at` | `TIMESTAMP` | False | `now()` |

**Primary Key:** `['id']`

**Index:** `ix_characters_slug` - `['slug']`



### `conversation_participants`

| Column | Type | Nullable | Default |
|---|---|---|---|
| `conversation_id` | `UUID` | False | `None` |
| `character_id` | `UUID` | False | `None` |
| `joined_at` | `TIMESTAMP` | False | `now()` |

**Primary Key:** `['conversation_id', 'character_id']`

**Foreign Key:** `['character_id']` -> `characters.['id']`

**Foreign Key:** `['conversation_id']` -> `conversations.['id']`



### `messages`

| Column | Type | Nullable | Default |
|---|---|---|---|
| `id` | `UUID` | False | `None` |
| `conversation_id` | `UUID` | False | `None` |
| `sender_type` | `VARCHAR(20)` | False | `None` |
| `sender_user_id` | `UUID` | True | `None` |
| `sender_character_id` | `UUID` | True | `None` |
| `content` | `TEXT` | False | `None` |
| `message_type` | `VARCHAR(20)` | False | `None` |
| `created_at` | `TIMESTAMP` | False | `now()` |

**Primary Key:** `['id']`

**Foreign Key:** `['conversation_id']` -> `conversations.['id']`

**Foreign Key:** `['sender_character_id']` -> `characters.['id']`

**Foreign Key:** `['sender_user_id']` -> `users.['id']`

**Check:** `ck_message_sender` - `sender_type::text = 'user'::text AND sender_user_id IS NOT NULL AND sender_character_id IS NULL OR sender_type::text = 'character'::text AND sender_character_id IS NOT NULL AND sender_user_id IS NULL`

**Index:** `ix_messages_conversation_id` - `['conversation_id']`



### `conversations`

| Column | Type | Nullable | Default |
|---|---|---|---|
| `id` | `UUID` | False | `None` |
| `user_id` | `UUID` | False | `None` |
| `title` | `VARCHAR(200)` | True | `None` |
| `conversation_type` | `VARCHAR(20)` | False | `None` |
| `created_at` | `TIMESTAMP` | False | `now()` |
| `updated_at` | `TIMESTAMP` | False | `now()` |
| `summary` | `TEXT` | True | `None` |
| `summary_message_count` | `INTEGER` | False | `0` |

**Primary Key:** `['id']`

**Foreign Key:** `['user_id']` -> `users.['id']`

**Index:** `ix_conversations_user_id` - `['user_id']`



### `user_memories`

| Column | Type | Nullable | Default |
|---|---|---|---|
| `id` | `UUID` | False | `None` |
| `user_id` | `UUID` | False | `None` |
| `category` | `VARCHAR(50)` | False | `None` |
| `content` | `TEXT` | False | `None` |
| `importance` | `INTEGER` | False | `None` |
| `confidence` | `DOUBLE PRECISION` | False | `None` |
| `created_at` | `TIMESTAMP` | False | `now()` |
| `updated_at` | `TIMESTAMP` | False | `now()` |

**Primary Key:** `['id']`

**Foreign Key:** `['user_id']` -> `users.['id']`

**Unique:** `['user_id', 'category', 'content']`

**Check:** `ck_user_memory_confidence` - `confidence >= 0::double precision AND confidence <= 1::double precision`

**Check:** `ck_user_memory_importance` - `importance >= 1 AND importance <= 10`

**Index:** `ix_user_memories_user_id` - `['user_id']`

**Index:** `uq_user_memory_user_category_content` - `['user_id', 'category', 'content']`



### `character_memories`

| Column | Type | Nullable | Default |
|---|---|---|---|
| `id` | `UUID` | False | `None` |
| `user_id` | `UUID` | False | `None` |
| `character_id` | `UUID` | False | `None` |
| `category` | `VARCHAR(50)` | False | `None` |
| `content` | `TEXT` | False | `None` |
| `importance` | `INTEGER` | False | `None` |
| `confidence` | `DOUBLE PRECISION` | False | `None` |
| `created_at` | `TIMESTAMP` | False | `now()` |
| `updated_at` | `TIMESTAMP` | False | `now()` |
| `memory_key` | `VARCHAR(100)` | True | `None` |
| `source_conversation_id` | `UUID` | True | `None` |
| `source_kind` | `VARCHAR(20)` | True | `None` |

Provenance only (where the character learned it): memories stay per user + character, never per conversation. `source_conversation_id` is `ON DELETE SET NULL`, so deleting a chat keeps the memory. Categories in use: interest, preference, personal, goal, hobby, event, relationship (free text, no DB check).

**Primary Key:** `['id']`

**Foreign Key:** `['character_id']` -> `characters.['id']`

**Foreign Key:** `['user_id']` -> `users.['id']`

**Foreign Key:** `['source_conversation_id']` -> `conversations.['id']` (ON DELETE SET NULL)

**Unique:** `['user_id', 'character_id', 'category', 'content']`

**Unique:** `['user_id', 'character_id', 'memory_key']`

**Check:** `ck_character_memory_confidence` - `confidence >= 0::double precision AND confidence <= 1::double precision`

**Check:** `ck_character_memory_importance` - `importance >= 1 AND importance <= 10`

**Check:** `ck_character_memory_source_kind` - `source_kind IS NULL OR source_kind IN ('direct', 'group')`

**Index:** `ix_character_memories_character_id` - `['character_id']`

**Index:** `ix_character_memories_user_id` - `['user_id']`

**Index:** `uq_character_memory_user_character_category_content` - `['user_id', 'character_id', 'category', 'content']`

**Index:** `uq_character_memory_user_character_key` - `['user_id', 'character_id', 'memory_key']`



### `character_relationships`

How one character feels about another, per user (directional: A->B and B->A are separate rows). Values 0..100, never shown to the user. Migration `c41d7e2a9b10`.

| Column | Type | Nullable | Default |
|---|---|---|---|
| `user_id` | `UUID` | False | `None` |
| `character_id` | `UUID` | False | `None` |
| `other_character_id` | `UUID` | False | `None` |
| `trust` | `SMALLINT` | False | `50` |
| `affection` | `SMALLINT` | False | `50` |
| `respect` | `SMALLINT` | False | `50` |
| `jealousy` | `SMALLINT` | False | `0` |
| `rivalry` | `SMALLINT` | False | `0` |
| `familiarity` | `SMALLINT` | False | `0` |
| `tension` | `SMALLINT` | False | `0` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | False | `now()` |

**Primary Key:** `['user_id', 'character_id', 'other_character_id']`

**Check:** every value between 0 and 100; `character_id <> other_character_id`. All three foreign keys `ON DELETE CASCADE`.



### `character_emotions`

A character's current mood per user (one row). Fades with time when read.

| Column | Type | Nullable | Default |
|---|---|---|---|
| `user_id` | `UUID` | False | `None` |
| `character_id` | `UUID` | False | `None` |
| `mood` | `VARCHAR(30)` | False | `None` |
| `intensity` | `SMALLINT` | False | `None` |
| `reason` | `TEXT` | True | `None` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | False | `now()` |

**Primary Key:** `['user_id', 'character_id']`

**Check:** `intensity` between 0 and 100. Foreign keys `ON DELETE CASCADE`.



### `conversations` (addition)

| Column | Type | Nullable | Default |
|---|---|---|---|
| `reflection_message_count` | `INTEGER` | False | `0` |

How many messages the group feelings reflection has already looked at (migration `d52e8f3b1c21`).
