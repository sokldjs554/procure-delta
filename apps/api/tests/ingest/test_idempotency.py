from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IngestRun, RawRecord, SourceRegistry
from app.services.ingest import ingest_raw_record
from app.sources.base import RawSourceRecord


@pytest.mark.asyncio
async def test_identical_raw_payload_is_stored_once_and_counted_as_duplicate(
    session: AsyncSession,
) -> None:
    source = SourceRegistry(
        code="mock-ingest-dedupe", display_name="Mock", base_url="https://example.test"
    )
    session.add(source)
    await session.flush()
    run = IngestRun(source_id=source.id, status="running")
    session.add(run)
    await session.flush()
    record = RawSourceRecord(source_record_id="notice-1", raw_payload={"title": "Synthetic"})

    first = await ingest_raw_record(session, source.id, record, ingest_run=run)
    second = await ingest_raw_record(session, source.id, record, ingest_run=run)
    await session.flush()

    assert first.created is True
    assert second.created is False
    assert run.created_count == 1
    assert run.duplicate_count == 1
    assert (
        await session.scalar(
            select(func.count()).select_from(RawRecord).where(RawRecord.source_id == source.id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_changed_raw_payload_creates_a_new_immutable_version(session: AsyncSession) -> None:
    source = SourceRegistry(
        code="mock-ingest-change", display_name="Mock", base_url="https://example.test"
    )
    session.add(source)
    await session.flush()

    first = await ingest_raw_record(
        session,
        source.id,
        RawSourceRecord(source_record_id="notice-1", raw_payload={"title": "v1"}),
    )
    second = await ingest_raw_record(
        session,
        source.id,
        RawSourceRecord(source_record_id="notice-1", raw_payload={"title": "v2"}),
    )
    await session.flush()

    assert first.created is True
    assert second.created is True
    assert first.payload_sha256 != second.payload_sha256
    assert (
        await session.scalar(
            select(func.count()).select_from(RawRecord).where(RawRecord.source_id == source.id)
        )
        == 2
    )
