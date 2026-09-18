from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IngestRun, RawRecord
from app.sources.base import RawSourceRecord


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    created: bool
    payload_sha256: str
    raw_record_id: UUID


def raw_record_checksum(source_id: UUID, record: RawSourceRecord) -> str:
    """Return a stable source-scoped fingerprint without mutating the raw payload."""
    payload = json.dumps(
        record.raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def ingest_raw_record(
    session: AsyncSession,
    source_id: UUID,
    record: RawSourceRecord,
    *,
    ingest_run: IngestRun | None = None,
) -> IngestOutcome:
    """Preserve an upstream envelope once per source, record id, and payload version."""
    checksum = raw_record_checksum(source_id, record)
    statement = (
        insert(RawRecord)
        .values(
            source_id=source_id,
            source_record_id=record.source_record_id,
            source_updated_at=record.source_updated_at,
            payload_json=dict(record.raw_payload),
            payload_sha256=checksum,
            http_etag=record.http_etag,
            http_last_modified=record.http_last_modified,
        )
        .on_conflict_do_nothing(constraint="uq_raw_record_payload")
        .returning(RawRecord.id)
    )
    raw_record_id = (await session.execute(statement)).scalar_one_or_none()
    created = raw_record_id is not None
    if raw_record_id is None:
        raw_record_id = await session.scalar(
            select(RawRecord.id).where(
                RawRecord.source_id == source_id,
                RawRecord.source_record_id == record.source_record_id,
                RawRecord.payload_sha256 == checksum,
            )
        )
        assert raw_record_id is not None
    if ingest_run is not None:
        if created:
            ingest_run.created_count += 1
        else:
            ingest_run.duplicate_count += 1
    return IngestOutcome(
        created=created, payload_sha256=checksum, raw_record_id=raw_record_id
    )
