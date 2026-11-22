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

**Primary Key:** `['id']`

**Foreign Key:** `['character_id']` -> `characters.['id']`

**Foreign Key:** `['user_id']` -> `users.['id']`

**Unique:** `['user_id', 'character_id', 'category', 'content']`

**Unique:** `['user_id', 'character_id', 'memory_key']`

**Check:** `ck_character_memory_confidence` - `confidence >= 0::double precision AND confidence <= 1::double precision`

**Check:** `ck_character_memory_importance` - `importance >= 1 AND importance <= 10`

**Index:** `ix_character_memories_character_id` - `['character_id']`

**Index:** `ix_character_memories_user_id` - `['user_id']`

**Index:** `uq_character_memory_user_character_category_content` - `['user_id', 'character_id', 'category', 'content']`

**Index:** `uq_character_memory_user_character_key` - `['user_id', 'character_id', 'memory_key']`

