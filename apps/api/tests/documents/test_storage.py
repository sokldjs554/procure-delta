from __future__ import annotations

import io

import pytest

from app.config import Settings
from app.documents.storage import (
    BlobTooLargeError,
    LocalBlobStore,
    S3BlobStore,
    configured_attachment_store,
    validate_blob_key,
)


@pytest.mark.asyncio
async def test_local_blob_store_round_trip_and_bounds(tmp_path) -> None:
    content = b"local attachment"
    key = "sha256/aa/" + "a" * 64 + ".blob"
    store = LocalBlobStore(tmp_path)

    await store.put(key, content)
    await store.put(key, content)
    assert await store.read(key, max_bytes=1024) == content
    with pytest.raises(BlobTooLargeError):
        await store.read(key, max_bytes=2)
    assert await store.ready() is True


def test_blob_key_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        validate_blob_key("../../secret")
    with pytest.raises(ValueError):
        validate_blob_key("sha256/aa/" + "a" * 63 + ".blob")


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **kwargs: object) -> None:
        del kwargs
        self.objects[(Bucket, Key)] = bytes(Body)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        content = self.objects[(Bucket, Key)]
        return {"ContentLength": len(content), "Body": io.BytesIO(content)}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop((Bucket, Key), None)


@pytest.mark.asyncio
async def test_s3_blob_store_uses_shared_prefix_and_readiness_probe() -> None:
    fake = FakeS3()
    store = S3BlobStore(bucket="bucket", prefix="/portfolio/", client=fake)
    key = "sha256/bb/" + "b" * 64 + ".blob"
    content = b"shared attachment"

    await store.put(key, content)
    assert fake.objects[("bucket", "portfolio/" + key)] == content
    assert await store.read(key, max_bytes=1024) == content
    assert await store.ready() is True
    assert set(fake.objects) == {("bucket", "portfolio/" + key)}


def test_configured_store_requires_bucket_for_s3() -> None:
    settings = Settings(attachment_storage_backend="s3", _env_file=None)
    with pytest.raises(ValueError, match="ATTACHMENT_S3_BUCKET"):
        configured_attachment_store(settings)


def test_render_database_url_and_single_cors_origin_are_normalized() -> None:
    settings = Settings(
        database_url="postgresql://user:pass@db.internal:5432/procure_delta",
        cors_origins="https://procure-delta-web.onrender.com",
        _env_file=None,
    )
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.cors_origins == ["https://procure-delta-web.onrender.com"]
