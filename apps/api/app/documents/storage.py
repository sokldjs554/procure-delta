from __future__ import annotations

import asyncio
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import uuid4

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from app.config import Settings

_BLOB_KEY = re.compile(r"^sha256/[0-9a-f]{2}/[0-9a-f]{64}\.blob$")


class BlobStoreError(OSError):
    pass


class BlobNotFoundError(BlobStoreError):
    pass


class BlobTooLargeError(BlobStoreError):
    pass


def validate_blob_key(key: str) -> str:
    if not _BLOB_KEY.fullmatch(key):
        raise ValueError("invalid attachment blob key")
    return key


@runtime_checkable
class AttachmentBlobStore(Protocol):
    async def put(self, key: str, content: bytes) -> None: ...

    async def read(self, key: str, *, max_bytes: int) -> bytes: ...

    async def ready(self) -> bool: ...


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        validated = validate_blob_key(key)
        path = (self.root / validated).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("attachment blob escapes configured root")
        return path

    async def put(self, key: str, content: bytes) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            return
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent, prefix=".incoming-"
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            with suppress(FileExistsError):
                os.link(temporary_name, destination)
        except OSError as exc:
            raise BlobStoreError("local attachment write failed") from exc
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    async def read(self, key: str, *, max_bytes: int) -> bytes:
        path = self._path(key)
        try:
            if path.stat().st_size > max_bytes:
                raise BlobTooLargeError("attachment exceeds configured size limit")
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise BlobNotFoundError("attachment blob not found") from exc
        except BlobTooLargeError:
            raise
        except OSError as exc:
            raise BlobStoreError("local attachment read failed") from exc
        if len(content) > max_bytes:
            raise BlobTooLargeError("attachment exceeds configured size limit")
        return content

    async def ready(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=self.root) as handle:
                handle.write(b"readiness")
                handle.flush()
            return True
        except OSError:
            return False


class S3BlobStore:
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("attachment S3 bucket is required")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client or boto3.client(
            "s3",
            region_name=region or None,
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
        )

    def _remote_key(self, key: str) -> str:
        validated = validate_blob_key(key)
        return f"{self.prefix}/{validated}" if self.prefix else validated

    def _probe_key(self) -> str:
        leaf = f"_health/{uuid4().hex}"
        return f"{self.prefix}/{leaf}" if self.prefix else leaf

    async def put(self, key: str, content: bytes) -> None:
        try:
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=self._remote_key(key),
                Body=content,
                ContentType="application/octet-stream",
            )
        except Exception as exc:
            raise BlobStoreError("shared attachment write failed") from exc

    async def read(self, key: str, *, max_bytes: int) -> bytes:
        try:
            response = await asyncio.to_thread(
                self.client.get_object,
                Bucket=self.bucket,
                Key=self._remote_key(key),
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise BlobNotFoundError("attachment blob not found") from exc
            raise BlobStoreError("shared attachment read failed") from exc
        except Exception as exc:
            raise BlobStoreError("shared attachment read failed") from exc

        body = response["Body"]
        try:
            size = int(response.get("ContentLength") or 0)
            if size > max_bytes:
                raise BlobTooLargeError("attachment exceeds configured size limit")
            content = await asyncio.to_thread(body.read, max_bytes + 1)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
        if len(content) > max_bytes:
            raise BlobTooLargeError("attachment exceeds configured size limit")
        return bytes(content)

    async def ready(self) -> bool:
        key = self._probe_key()
        try:
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=b"readiness",
                ContentType="application/octet-stream",
            )
            await asyncio.to_thread(
                self.client.delete_object,
                Bucket=self.bucket,
                Key=key,
            )
            return True
        except Exception:
            return False


def _secret(value: Any) -> str | None:
    if value is None:
        return None
    raw = value.get_secret_value()
    return raw or None


def configured_attachment_store(
    settings: Settings, *, local_root: Path | None = None
) -> AttachmentBlobStore:
    if settings.attachment_storage_backend == "local":
        return LocalBlobStore(local_root or settings.attachment_storage_path)
    if not settings.attachment_s3_bucket:
        raise ValueError("ATTACHMENT_S3_BUCKET is required for S3 storage")
    return S3BlobStore(
        bucket=settings.attachment_s3_bucket,
        prefix=settings.attachment_s3_prefix,
        region=settings.attachment_s3_region,
        endpoint_url=settings.attachment_s3_endpoint_url,
        access_key_id=_secret(settings.attachment_s3_access_key_id),
        secret_access_key=_secret(settings.attachment_s3_secret_access_key),
    )
