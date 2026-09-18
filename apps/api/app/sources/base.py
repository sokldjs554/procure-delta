from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class AttachmentRef(BaseModel):
    """An immutable reference to an upstream attachment."""

    model_config = ConfigDict(frozen=True)

    attachment_id: str
    filename: str
    url: str
    media_type: str | None = None
    fixture_key: str | None = None


class RawSourceRecord(BaseModel):
    """An immutable envelope that keeps the upstream payload unparsed."""

    model_config = ConfigDict(frozen=True)

    source_record_id: str
    raw_payload: Mapping[str, Any]
    source_url: str | None = None
    http_etag: str | None = None
    http_last_modified: str | None = None
    source_updated_at: datetime | None = None


class DiscoveryPage(BaseModel):
    """One deterministic page of source record references."""

    model_config = ConfigDict(frozen=True)

    records: tuple[RawSourceRecord, ...] = Field(default_factory=tuple)
    next_cursor: str | None = None


@runtime_checkable
class SourceAdapter(Protocol):
    """Common async contract for public-data source adapters."""

    async def discover(self, cursor: str | None) -> DiscoveryPage: ...

    async def fetch_record(self, source_record_id: str) -> RawSourceRecord: ...

    async def fetch_attachments(self, record: RawSourceRecord) -> list[AttachmentRef]: ...
