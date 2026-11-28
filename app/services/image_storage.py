"""Where generated pictures are kept.

The database only stores a KEY; the bytes live behind this interface so the
folder can later be swapped for object storage (R2/S3) without touching the
callers.
"""

import asyncio
import logging
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)

_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
# Keys are always <32 hex>.<ext>, in every backend: a key from a database row
# or a callback can never name anything else (no paths, no other objects).
_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg|jpeg|webp)$")


class ImageStorageError(OSError):
    """The storage backend failed (network, credentials, permissions).

    An OSError on purpose: callers already treat unreadable pictures as
    "skip this one". It is NOT FileNotFoundError: a failed read does not mean
    the picture is gone.
    """


class ImageStorage(ABC):
    @abstractmethod
    async def save(self, data: bytes, extension: str = "png") -> str:
        """Store the bytes and return a key."""

    @abstractmethod
    async def load(self, key: str) -> bytes:
        """Return the bytes of a stored picture."""


class LocalImageStorage(ImageStorage):
    _EXTENSIONS = _EXTENSIONS

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)

    async def save(self, data: bytes, extension: str = "png") -> str:
        key = _new_key(data, extension)
        self.directory.mkdir(parents=True, exist_ok=True)
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


def _new_key(data: bytes, extension: str) -> str:
    if extension not in _EXTENSIONS:
        raise ValueError("Unsupported image type.")
    if not data:
        raise ValueError("Empty image.")
    return f"{uuid.uuid4().hex}.{extension}"


_CONTENT_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


class R2ImageStorage(ImageStorage):
    """Pictures in a private Cloudflare R2 bucket (S3-compatible).

    Same keys as the local folder, so database rows and the cache keep working
    and `scripts/migrate_images_to_r2.py` can copy old files across unchanged.
    The bucket stays private: pictures are read through the bot, never linked.
    boto3 is synchronous, so every call runs in a worker thread.
    """

    def __init__(self, client, bucket: str, prefix: str = ""):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""

    @classmethod
    def from_settings(cls, *, account_id, access_key_id, secret_access_key, bucket, endpoint="", prefix=""):
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=endpoint or f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(
                connect_timeout=10,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        return cls(client, bucket, prefix)

    def _object(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def save(self, data: bytes, extension: str = "png") -> str:
        key = _new_key(data, extension)
        await self.put(key, data)
        return key

    async def put(self, key: str, data: bytes) -> None:
        """Store bytes under an existing key (used by the migration script)."""
        if not _KEY_PATTERN.fullmatch(key):
            raise ValueError("Bad image key.")
        try:
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=self._object(key),
                Body=data,
                ContentType=_CONTENT_TYPES[key.rsplit(".", 1)[1]],
            )
        except Exception as exc:
            logger.error("R2 upload failed: %s", type(exc).__name__)
            raise ImageStorageError("Could not store the picture.") from exc

    async def exists(self, key: str) -> bool:
        if not _KEY_PATTERN.fullmatch(key):
            return False
        try:
            await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=self._object(key))
            return True
        except Exception as exc:
            if _is_missing(exc):
                return False
            logger.error("R2 lookup failed: %s", type(exc).__name__)
            raise ImageStorageError("Could not reach picture storage.") from exc

    async def load(self, key: str) -> bytes:
        if not _KEY_PATTERN.fullmatch(key):
            raise FileNotFoundError("Unknown image key.")
        try:
            response = await asyncio.to_thread(
                self.client.get_object, Bucket=self.bucket, Key=self._object(key)
            )
            return await asyncio.to_thread(response["Body"].read)
        except Exception as exc:
            if _is_missing(exc):
                raise FileNotFoundError("Unknown image key.") from exc
            logger.error("R2 download failed: %s", type(exc).__name__)
            raise ImageStorageError("Could not read the picture.") from exc


def _is_missing(exc: Exception) -> bool:
    error = getattr(exc, "response", {}).get("Error", {})
    return error.get("Code") in {"NoSuchKey", "404", "NotFound"}


def build_image_storage(settings) -> ImageStorage:
    """The storage the settings ask for. A half-configured R2 is a mistake
    worth stopping for at start-up, not a silent fallback to the local folder."""
    kind = (settings.IMAGE_STORAGE or "local").strip().lower()
    if kind == "local":
        return LocalImageStorage(settings.IMAGE_STORAGE_DIR)
    if kind != "r2":
        raise RuntimeError("IMAGE_STORAGE must be 'local' or 'r2'.")

    missing = [
        name
        for name in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
        if not getattr(settings, name)
    ]
    if not (settings.R2_ACCOUNT_ID or settings.R2_ENDPOINT):
        missing.append("R2_ACCOUNT_ID")
    if missing:
        raise RuntimeError("IMAGE_STORAGE=r2 needs " + ", ".join(missing) + ".")

    return R2ImageStorage.from_settings(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket=settings.R2_BUCKET,
        endpoint=settings.R2_ENDPOINT,
        prefix=settings.R2_PREFIX,
    )
