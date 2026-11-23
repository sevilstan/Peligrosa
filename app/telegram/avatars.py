import re
from dataclasses import dataclass
from pathlib import Path

from aiogram.types import FSInputFile, Message

# Same shape as character slugs; also keeps file lookups inside the folder.
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[2] / "characters" / "avatars"


@dataclass(frozen=True)
class AvatarSource:
    key: str
    media: object  # Telegram file_id, https URL, or FSInputFile


class AvatarProvider:
    """Finds a character's picture and remembers Telegram file_ids.

    Source order: characters/avatars/<slug>.<ext>, then the character's
    avatar_url (https only). Once Telegram has a file, its file_id is reused
    so the picture is not uploaded again on every slide change.
    """

    def __init__(self, directory: Path | str | None = None):
        self.directory = Path(directory) if directory is not None else DEFAULT_DIRECTORY
        self._file_ids: dict[str, str] = {}

    def resolve(self, slug: str, avatar_url: str | None) -> AvatarSource | None:
        path = self._local_path(slug)

        if path is not None:
            key = f"file:{path.name}:{path.stat().st_mtime_ns}"
            fresh: object = FSInputFile(path)
        elif avatar_url and avatar_url.startswith("https://"):
            key = f"url:{avatar_url}"
            fresh = avatar_url
        else:
            return None

        return AvatarSource(key=key, media=self._file_ids.get(key, fresh))

    def remember(self, source: AvatarSource, sent: Message) -> None:
        if sent.photo:
            self._file_ids[source.key] = sent.photo[-1].file_id

    def forget(self, source: AvatarSource) -> None:
        self._file_ids.pop(source.key, None)

    def _local_path(self, slug: str) -> Path | None:
        if not _SLUG_PATTERN.fullmatch(slug):
            return None
        for extension in _EXTENSIONS:
            path = self.directory / f"{slug}{extension}"
            if path.is_file():
                return path
        return None
