"""Delete again the data of users whose data was wiped by an operator, after restoring a backup.

    python -m scripts.reapply_deletions deleted_users.txt

The file can be plain user ids (one per line) or log lines; the bot logs
"User data deleted: user_id=<id>" at every deletion, so
    grep "User data deleted" bot.log > deleted_users.txt
is enough. A backup taken before a deletion would otherwise bring that data
back. Safe to run repeatedly.
"""

import asyncio
import sys

from app.database.session import SessionLocal
from app.models.user import User
from app.services.user_data_service import UserDataService, extract_user_ids


async def main(path: str) -> int:
    if SessionLocal is None:
        print("DATABASE_URL is not set. Check your .env file.", file=sys.stderr)
        return 1

    with open(path, encoding="utf-8") as handle:
        user_ids = extract_user_ids(handle.read())

    done = missing = 0
    async with SessionLocal() as session:
        for user_id in user_ids:
            if await session.get(User, user_id) is None:
                missing += 1
                continue
            await UserDataService(session).delete_all(user_id)
            done += 1

    print(f"Deleted again: {done}. Not in this database: {missing}.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.reapply_deletions <file>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
