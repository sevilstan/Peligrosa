# Character definitions

Peligrosa characters are platform-managed. Users do not create their own
characters.

Each character's static identity is stored in a separate UTF-8 YAML file:

```text
characters/
  elena.yaml
  natalie.yaml
```

The filename must match the character's database `slug`. The YAML `slug`
must match both the filename and the database row.

## Fields

- `name`: character display name.
- `slug`: stable identifier; lowercase letters, numbers and hyphens.
- `description`: short character identity.
- `profile` (optional): the card shown in the character slider and facts the
  character knows about herself: `age` (18 or more), `city`, `occupation`,
  `bio` (short life story, up to 600 characters) and `highlights` (up to 5
  short key traits). Missing parts are left out of the card.
- `personality`: structured lists such as `core_traits`, `speech_style`,
  `values`, `likes`, `dislikes`, `emotional_tendencies` and
  `social_behavior`.
- `system_prompt`: character-specific behavioral instructions.

Personality sections are lists of strings. New sections can be added without
changing the loader.

## Data ownership

YAML contains platform-defined, mostly static character information.
PostgreSQL remains responsible for user-specific and changing data:

- conversations and messages;
- each user's private memories for each character;
- emotions and relationship state;
- other runtime state that changes through interaction.

The loader currently falls back to the existing database character fields
when a character's YAML file does not exist. This allows definitions to be
migrated one character at a time. Once all active characters have YAML files,
we can remove that compatibility fallback in a separate change.

## Safety

Definitions are loaded with PyYAML's `safe_load`. Do not use YAML tags that
construct Python objects. A malformed existing YAML file raises an error
instead of silently falling back to database values.


## Export existing characters

To create the first YAML files from the character rows already in your local
PostgreSQL database, run this from the project root:

```powershell
python -m scripts.export_characters_to_yaml
```

The exporter includes every existing character and never overwrites a YAML
file by default. Review the generated files and enrich the structured
personality sections afterward.

Only use `--overwrite` if you intentionally want current database values to
replace existing YAML definitions:

```powershell
python -m scripts.export_characters_to_yaml --overwrite
```

Do not run the overwrite option after manually improving a YAML personality
unless you intend to discard those edits.
