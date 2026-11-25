"""Export chats for model training, without users who deleted their data.

    python -m scripts.export_training_data --out data/train.jsonl
    python -m scripts.export_training_data --deleted-pseudonyms

Needs TRAINING_EXPORT_SALT (16+ characters, private, never changed) in .env.
Users are pseudonymized; the chat text itself may still contain personal
details, so keep the output protected and only on systems you control.
--deleted-pseudonyms prints everyone who used /deletedata: remove those
pseudonyms from exports you made earlier.
"""

import argparse
import asyncio
import json
import sys

from app.core.config import settings
from app.database.session import SessionLocal
from app.services.training_export_service import TrainingExportService


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", help="JSONL file to write (one conversation per line)")
    group.add_argument("--deleted-pseudonyms", action="store_true")
    args = parser.parse_args(argv)

    if SessionLocal is None:
        print("DATABASE_URL is not set. Check your .env file.", file=sys.stderr)
        return 1

    try:
        async with SessionLocal() as session:
            service = TrainingExportService(session, settings.TRAINING_EXPORT_SALT)

            if args.deleted_pseudonyms:
                for value in await service.deleted_pseudonyms():
                    print(value)
                return 0

            count = 0
            with open(args.out, "w", encoding="utf-8") as handle:
                async for record in service.conversations():
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1
            print(f"Wrote {count} conversations to {args.out}")
            return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
