"""Where generated pictures are kept.

The database only stores a KEY; the bytes live behind this interface so the
folder can later be swapped for object storage (R2/S3) without touching the
callers.
"""

import uuid
from abc import ABC, abstractmethod
from pathlib import Path


class ImageStorage(ABC):
    @abstractmethod
    async def save(self, data: bytes, extension: str = "png") -> str:
        """Store the bytes and return a key."""

    @abstractmethod
    async def load(self, key: str) -> bytes:
        """Return the bytes of a stored picture."""


class LocalImageStorage(ImageStorage):
    _EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)

    async def save(self, data: bytes, extension: str = "png") -> str:
        if extension not in self._EXTENSIONS:
            raise ValueError("Unsupported image type.")
        if not data:
            raise ValueError("Empty image.")

        self.directory.mkdir(parents=True, exist_ok=True)
        key = f"{uuid.uuid4().hex}.{extension}"
        (self.directory / key).write_bytes(data)
        return key

    async def load(self, key: str) -> bytes:
        # The key may come from a database row or a callback: it must be a
        # plain file name that exists in OUR folder.
        path = (self.directory / key).resolve()
        if (
            Path(key).name != key
            or path.parent != self.directory.resolve()
            or not path.is_file()
        ):
            raise FileNotFoundError("Unknown image key.")
        return path.read_bytes()
