"""Copy the local picture folder into the R2 bucket, keeping every key.

Safe to run again: files already in the bucket are skipped. Nothing is deleted
locally. Run it once after setting IMAGE_STORAGE=r2 (or before switching, with
the R2_* settings filled in):

    python -m scripts.migrate_images_to_r2 [--dry-run]
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

from app.core.config import settings
from app.services.image_storage import R2ImageStorage, build_image_storage

_KEY = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg|jpeg|webp)$")


async def migrate(directory: Path, storage: R2ImageStorage, dry_run: bool = False) -> dict[str, int]:
    counts = {"uploaded": 0, "skipped": 0, "ignored": 0, "failed": 0}
    for path in sorted(directory.glob("*")):
        if not path.is_file() or not _KEY.fullmatch(path.name):
            counts["ignored"] += 1
            continue
        try:
            if await storage.exists(path.name):
                counts["skipped"] += 1
                continue
            if not dry_run:
                await storage.put(path.name, path.read_bytes())
            counts["uploaded"] += 1
        except OSError as exc:
            print(f"FAILED {path.name}: {type(exc).__name__}", file=sys.stderr)
            counts["failed"] += 1
    return counts


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="count only, upload nothing")
    args = parser.parse_args()

    settings.IMAGE_STORAGE = "r2"
    storage = build_image_storage(settings)
    directory = Path(settings.IMAGE_STORAGE_DIR)
    if not directory.is_dir():
        print(f"No local folder at {directory}; nothing to copy.")
        return 0

    counts = await migrate(directory, storage, args.dry_run)
    print(("DRY RUN " if args.dry_run else "") + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
