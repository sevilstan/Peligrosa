"""Cloudflare R2 picture storage, against a fake S3 client (no network)."""

import asyncio
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from app.services.image_storage import (
    ImageStorageError,
    LocalImageStorage,
    R2ImageStorage,
    build_image_storage,
)
from scripts.migrate_images_to_r2 import migrate

PNG = b"\x89PNG\r\n\x1a\n" + b"data"
KEY = "a" * 32 + ".png"


def error(code):
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "Op")


class FakeBody:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


class FakeS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.fail_with: Exception | None = None

    def put_object(self, Bucket, Key, Body, ContentType):
        if self.fail_with:
            raise self.fail_with
        self.objects[(Bucket, Key)] = (Body, ContentType)

    def get_object(self, Bucket, Key):
        if self.fail_with:
            raise self.fail_with
        if (Bucket, Key) not in self.objects:
            raise error("NoSuchKey")
        return {"Body": FakeBody(self.objects[(Bucket, Key)][0])}

    def head_object(self, Bucket, Key):
        if self.fail_with:
            raise self.fail_with
        if (Bucket, Key) not in self.objects:
            raise error("404")
        return {}


def run(coro):
    return asyncio.run(coro)


def test_save_then_load_round_trip_with_a_content_type():
    s3 = FakeS3()
    storage = R2ImageStorage(s3, "pics")

    async def go():
        key = await storage.save(PNG, "png")
        return key, await storage.load(key)

    key, data = run(go())
    assert data == PNG
    assert len(key) == 36 and key.endswith(".png")  # same key shape as the local folder
    assert s3.objects[("pics", key)][1] == "image/png"


def test_jpeg_gets_its_own_content_type():
    s3 = FakeS3()
    key = run(R2ImageStorage(s3, "pics").save(b"x", "jpg"))
    assert s3.objects[("pics", key)][1] == "image/jpeg"


def test_prefix_is_applied_to_every_object():
    s3 = FakeS3()
    storage = R2ImageStorage(s3, "pics", prefix="/prod/")
    key = run(storage.save(PNG))
    assert ("pics", f"prod/{key}") in s3.objects
    assert run(storage.load(key)) == PNG


def test_save_refuses_bad_input():
    storage = R2ImageStorage(FakeS3(), "pics")
    with pytest.raises(ValueError):
        run(storage.save(b"", "png"))
    with pytest.raises(ValueError):
        run(storage.save(PNG, "exe"))


@pytest.mark.parametrize("key", ["../x.png", "a/b.png", "abc.png", "A" * 32 + ".png", KEY + "x", "", KEY[:-3] + "gif"])
def test_odd_keys_are_unknown_and_never_reach_the_bucket(key):
    s3 = FakeS3()
    s3.fail_with = AssertionError("the bucket must not be asked")
    storage = R2ImageStorage(s3, "pics")
    with pytest.raises(FileNotFoundError):
        run(storage.load(key))
    assert run(storage.exists(key)) is False


def test_a_missing_object_is_file_not_found():
    storage = R2ImageStorage(FakeS3(), "pics")
    with pytest.raises(FileNotFoundError):
        run(storage.load(KEY))
    assert run(storage.exists(KEY)) is False


def test_other_failures_are_storage_errors_not_missing_files():
    s3 = FakeS3()
    storage = R2ImageStorage(s3, "pics")
    s3.fail_with = error("AccessDenied")

    for call in (storage.load(KEY), storage.exists(KEY), storage.save(PNG)):
        with pytest.raises(ImageStorageError) as caught:
            run(call)
        assert not isinstance(caught.value, FileNotFoundError)
        assert isinstance(caught.value, OSError)  # callers already skip OSError


# ------------------------------------------------------------ settings


def cfg(**kw):
    base = dict(
        IMAGE_STORAGE="r2", IMAGE_STORAGE_DIR="x", R2_ACCOUNT_ID="acc", R2_ACCESS_KEY_ID="k",
        R2_SECRET_ACCESS_KEY="s", R2_BUCKET="b", R2_ENDPOINT="", R2_PREFIX="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_factory_builds_local_or_r2(tmp_path):
    assert isinstance(build_image_storage(cfg(IMAGE_STORAGE="local", IMAGE_STORAGE_DIR=str(tmp_path))), LocalImageStorage)
    storage = build_image_storage(cfg())
    assert isinstance(storage, R2ImageStorage) and storage.bucket == "b"
    assert storage.client.meta.endpoint_url == "https://acc.r2.cloudflarestorage.com"


def test_half_configured_r2_stops_start_up_and_names_the_gap():
    for missing in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_ACCOUNT_ID"):
        with pytest.raises(RuntimeError, match=missing):
            build_image_storage(cfg(**{missing: ""}))

    # The message names settings, never their values.
    with pytest.raises(RuntimeError) as caught:
        build_image_storage(cfg(R2_BUCKET="", R2_SECRET_ACCESS_KEY="topsecret", R2_ACCESS_KEY_ID="topkey"))
    assert "topsecret" not in str(caught.value) and "topkey" not in str(caught.value)

    with pytest.raises(RuntimeError, match="local' or 'r2"):
        build_image_storage(cfg(IMAGE_STORAGE="s3"))


# ------------------------------------------------------------ migration


def test_migration_copies_keeps_keys_and_is_repeatable(tmp_path):
    (tmp_path / KEY).write_bytes(PNG)
    (tmp_path / ("b" * 32 + ".webp")).write_bytes(b"w")
    (tmp_path / "notes.txt").write_text("ignore me")
    s3 = FakeS3()
    storage = R2ImageStorage(s3, "pics")

    first = run(migrate(tmp_path, storage))
    assert first == {"uploaded": 2, "skipped": 0, "ignored": 1, "failed": 0}
    assert run(storage.load(KEY)) == PNG
    assert (tmp_path / KEY).exists()  # nothing is deleted locally

    second = run(migrate(tmp_path, storage))
    assert second == {"uploaded": 0, "skipped": 2, "ignored": 1, "failed": 0}


def test_migration_dry_run_uploads_nothing_and_failures_are_counted(tmp_path):
    (tmp_path / KEY).write_bytes(PNG)
    s3 = FakeS3()
    storage = R2ImageStorage(s3, "pics")

    assert run(migrate(tmp_path, storage, dry_run=True))["uploaded"] == 1
    assert s3.objects == {}

    s3.fail_with = error("AccessDenied")
    assert run(migrate(tmp_path, storage))["failed"] == 1
