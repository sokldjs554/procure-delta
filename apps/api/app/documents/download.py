from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import random
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.documents.storage import AttachmentBlobStore, LocalBlobStore
from app.documents.synthetic_fixtures import load_packaged_fixture

ALLOWED_MEDIA_TYPES = {
    "application/pdf",
    "text/html",
    "application/xhtml+xml",
    "application/x-hwp",
    "application/haansofthwp",
}
MAX_REDIRECTS = 3
MAX_ATTEMPTS = 3


class UnsafeAttachmentURLError(ValueError):
    """The attachment URL violates the trusted-source network boundary."""


@dataclass(frozen=True, slots=True)
class AttachmentDownloadRef:
    source_url: str
    filename: str
    declared_media_type: str | None
    allowed_source_host: str
    fixture_key: str | None = None


@dataclass(frozen=True, slots=True)
class StoredAttachment:
    sha256: str
    byte_size: int
    media_type: str
    filename: str
    storage_key: str
    original_bytes: bytes


def sanitize_filename(filename: str) -> str:
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^\w.()-]+", "_", leaf, flags=re.UNICODE).strip("._")
    return (cleaned or "attachment")[:255]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _resolve_public_addresses(hostname: str) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    addresses = await asyncio.wait_for(
        loop.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM), timeout=5.0
    )
    resolved = tuple(dict.fromkeys(item[4][0] for item in addresses))
    if not resolved or any(not _is_public(address) for address in resolved):
        raise UnsafeAttachmentURLError("attachment host resolves to a non-public address")
    return resolved


async def _validated_target(url: str, allowed_host: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise UnsafeAttachmentURLError("attachment URLs require credential-free HTTPS")
    hostname = parsed.hostname
    if hostname is None or hostname.lower() != allowed_host.lower():
        raise UnsafeAttachmentURLError("attachment host is not allowed for this source")
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None:
        if not _is_public(hostname):
            raise UnsafeAttachmentURLError("attachment host resolves to a non-public address")
        address = hostname
    else:
        address = (await _resolve_public_addresses(hostname))[0]
    port = parsed.port
    pinned_host = f"[{address}]" if ":" in address else address
    netloc = f"{pinned_host}:{port}" if port is not None else pinned_host
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, "")), hostname


def _detect_media_type(content: bytes, header: str | None) -> str:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    prefix = content[:1024].lstrip().lower()
    if prefix.startswith((b"<!doctype html", b"<html", b"<h1", b"<p")):
        return "text/html"
    if content.startswith(b"HWP Document File"):
        return "application/x-hwp"
    normalized = (header or "").split(";", 1)[0].strip().lower()
    if normalized in ALLOWED_MEDIA_TYPES:
        return normalized
    raise ValueError("unsupported attachment content type")


async def download_attachment(
    ref: AttachmentDownloadRef,
    *,
    client: httpx.AsyncClient | None = None,
    storage_root: Path | None = None,
    blob_store: AttachmentBlobStore | None = None,
    max_bytes: int = 10 * 1024 * 1024,
) -> StoredAttachment:
    """Download bounded trusted-source bytes and store them by content checksum."""
    if ref.fixture_key is not None:
        content = load_packaged_fixture(ref.fixture_key)
        response_media = ref.declared_media_type
    else:
        url = ref.source_url
        owned_client = client is None
        active_client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False
        )
        try:
            async with asyncio.timeout(30.0):
                for attempt in range(MAX_ATTEMPTS):
                    try:
                        redirects = 0
                        while True:
                            pinned_url, tls_hostname = await _validated_target(
                                url, ref.allowed_source_host
                            )
                            async with active_client.stream(
                                "GET",
                                pinned_url,
                                headers={"host": tls_hostname},
                                extensions={"sni_hostname": tls_hostname.encode()},
                            ) as response:
                                if response.status_code in {301, 302, 303, 307, 308}:
                                    if redirects == MAX_REDIRECTS:
                                        raise UnsafeAttachmentURLError(
                                            "attachment redirect limit exceeded"
                                        )
                                    location = response.headers.get("location")
                                    if not location:
                                        raise UnsafeAttachmentURLError(
                                            "attachment redirect has no location"
                                        )
                                    url = urljoin(url, location)
                                    redirects += 1
                                    continue
                                if response.status_code == 429 or response.status_code >= 500:
                                    response.raise_for_status()
                                response.raise_for_status()
                                declared_length = response.headers.get("content-length")
                                if declared_length is not None and int(declared_length) > max_bytes:
                                    raise ValueError(
                                        "attachment content length exceeds configured limit"
                                    )
                                body = bytearray()
                                async for chunk in response.aiter_bytes():
                                    body.extend(chunk)
                                    if len(body) > max_bytes:
                                        raise ValueError(
                                            "attachment actual bytes exceed configured limit"
                                        )
                                content = bytes(body)
                                response_media = response.headers.get("content-type")
                                break
                            break
                        break
                    except (
                        httpx.TransportError,
                        httpx.TimeoutException,
                        httpx.HTTPStatusError,
                    ) as error:
                        retryable_status = isinstance(error, httpx.HTTPStatusError) and (
                            error.response.status_code == 429 or error.response.status_code >= 500
                        )
                        if not retryable_status and not isinstance(error, httpx.TransportError):
                            raise
                        if attempt + 1 == MAX_ATTEMPTS:
                            raise
                        await asyncio.sleep((2**attempt) * 0.05 + random.uniform(0, 0.02))
        finally:
            if owned_client:
                await active_client.aclose()
    if len(content) > max_bytes:
        raise ValueError("attachment actual bytes exceed configured limit")
    media_type = _detect_media_type(content, response_media or ref.declared_media_type)
    checksum = hashlib.sha256(content).hexdigest()
    storage_key = f"sha256/{checksum[:2]}/{checksum}.blob"
    root = storage_root or Path(os.getenv("ATTACHMENT_STORAGE_PATH", "/var/lib/procure-delta"))
    store = blob_store or LocalBlobStore(root)
    await store.put(storage_key, content)
    return StoredAttachment(
        sha256=checksum,
        byte_size=len(content),
        media_type=media_type,
        filename=sanitize_filename(ref.filename),
        storage_key=storage_key,
        original_bytes=content,
    )
