"""Create or refresh database rows for every YAML file in characters/.

Run from the project root:
    python -m scripts.sync_characters

The Telegram bot does the same thing every time it starts; use this script to
do it by hand (for example to check a new character file before restarting).
Nothing is ever deleted, and active status, order and avatar_url of existing
characters are left alone.
"""

import asyncio
import sys

from app.core.logging_config import setup_logging
from app.database.session import SessionLocal
from app.services.character_sync_service import CharacterSyncService


async def main() -> int:
    if SessionLocal is None:
        print("DATABASE_URL is not set. Check your .env file.", file=sys.stderr)
        return 1

    async with SessionLocal() as session:
        result = await CharacterSyncService(session).sync()

    print(f"created:   {', '.join(result.created) or '-'}")
    print(f"updated:   {', '.join(result.updated) or '-'}")
    print(f"unchanged: {', '.join(result.unchanged) or '-'}")
    for slug, reason in result.failed.items():
        print(f"FAILED {slug}: {reason}", file=sys.stderr)

    return 1 if result.failed else 0


if __name__ == "__main__":
    setup_logging()
    raise SystemExit(asyncio.run(main()))
