from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    Attachment,
    DocumentParse,
    JobFailure,
    Opportunity,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
)
from app.sources.base import AttachmentRef, RawSourceRecord
from app.workers.jobs import job_key, reconcile_pending_documents


class DocumentAdapter:
    def __init__(self, *, bad_records: set[str] | None = None) -> None:
        self.bad_records = bad_records or set()
        self.calls: list[str] = []

    async def fetch_attachments(self, record: RawSourceRecord) -> list[AttachmentRef]:
        self.calls.append(record.source_record_id)
        bad = record.source_record_id in self.bad_records
        return [
            AttachmentRef(
                attachment_id=f"{record.source_record_id}-attachment",
                filename="attachment.html",
                url=f"https://example.invalid/{record.source_record_id}.html",
                media_type="text/html",
                fixture_key="missing.html" if bad else "synthetic-specification.html",
            )
        ]


class TransientDocumentAdapter(DocumentAdapter):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    async def fetch_attachments(self, record: RawSourceRecord) -> list[AttachmentRef]:
        self.calls.append(record.source_record_id)
        if self.failures:
            self.failures -= 1
            import httpx

            raise httpx.ConnectError("synthetic attachment outage")
        return await super().fetch_attachments(record)


@pytest_asyncio.fixture(autouse=True)
async def cleanup_document_reconciliation_rows(
    worker_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    yield
    async with worker_session_factory() as cleanup:
        source_ids = (
            await cleanup.scalars(
                select(SourceRegistry.id).where(SourceRegistry.code.like("documents-%"))
            )
        ).all()
        if not source_ids:
            return
        raw_ids = (
            await cleanup.scalars(select(RawRecord.id).where(RawRecord.source_id.in_(source_ids)))
        ).all()
        version_rows = (
            await cleanup.execute(
                select(OpportunityVersion.id, OpportunityVersion.opportunity_id).where(
                    OpportunityVersion.raw_record_id.in_(raw_ids)
                )
            )
        ).all()
        version_ids = [row.id for row in version_rows]
        opportunity_ids = [row.opportunity_id for row in version_rows]
        attachment_ids = (
            await cleanup.scalars(
                select(Attachment.id).where(Attachment.opportunity_version_id.in_(version_ids))
            )
        ).all()
        if attachment_ids:
            await cleanup.execute(
                delete(DocumentParse).where(DocumentParse.attachment_id.in_(attachment_ids))
            )
        if version_ids:
            await cleanup.execute(
                delete(Attachment).where(Attachment.opportunity_version_id.in_(version_ids))
            )
            await cleanup.execute(
                delete(OpportunityVersion).where(OpportunityVersion.id.in_(version_ids))
            )
        if raw_ids:
            await cleanup.execute(delete(RawRecord).where(RawRecord.id.in_(raw_ids)))
        if opportunity_ids:
            await cleanup.execute(delete(Opportunity).where(Opportunity.id.in_(opportunity_ids)))
        await cleanup.execute(
            delete(JobFailure).where(
                JobFailure.payload_json["source_code"].astext.like("documents-%")
            )
        )
        await cleanup.execute(delete(SourceRegistry).where(SourceRegistry.id.in_(source_ids)))
        await cleanup.commit()


async def _seed_versions(
    factory: async_sessionmaker[AsyncSession], source_code: str, record_ids: list[str]
) -> tuple[UUID, dict[str, UUID]]:
    raw_ids: dict[str, UUID] = {}
    async with factory() as session:
        source = SourceRegistry(
            code=source_code, display_name="Documents", base_url="https://example.invalid"
        )
        session.add(source)
        await session.flush()
        source_id = source.id
        id_base = (uuid5(NAMESPACE_URL, source_code).int >> 16) << 16
        for sequence, record_id in enumerate(record_ids, start=1):
            raw = RawRecord(
                id=UUID(int=id_base + sequence),
                source_id=source.id,
                source_record_id=record_id,
                payload_json={"title": record_id},
                payload_sha256=f"{sequence:064x}",
                normalization_status="normalized",
            )
            opportunity = Opportunity(
                canonical_key=f"{source_code}:{record_id}", title=record_id, buyer_name="Buyer"
            )
            session.add_all([raw, opportunity])
            await session.flush()
            session.add(
                OpportunityVersion(
                    opportunity_id=opportunity.id,
                    raw_record_id=raw.id,
                    version_number=1,
                    source_record_id=record_id,
                    normalized_json={},
                    normalized_sha256=f"{sequence + 10:064x}",
                )
            )
            raw_ids[record_id] = raw.id
        await session.commit()
    return source_id, raw_ids


@pytest.mark.asyncio
async def test_document_reconciliation_isolates_failed_record_and_continues(
    worker_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, raw_ids = await _seed_versions(
        worker_session_factory, "documents-isolation", ["first-bad", "second-good"]
    )
    adapter = DocumentAdapter(bad_records={"first-bad"})
    monkeypatch.setattr(
        "app.workers.jobs.source_adapters", lambda: {"documents-isolation": adapter}
    )

    result = await reconcile_pending_documents(
        {
            "session_factory": worker_session_factory,
            "attachment_storage_path": tmp_path,
        }
    )

    async with worker_session_factory() as verify:
        failure = await verify.scalar(
            select(JobFailure).where(JobFailure.job_type == "parse_documents")
        )
        assert result == {"processed": 1, "failed": 1}
        assert adapter.calls == ["first-bad", "second-good"]
        assert failure is not None
        failed_version = (
            await verify.scalars(
                select(OpportunityVersion).where(
                    OpportunityVersion.raw_record_id == raw_ids["first-bad"]
                )
            )
        ).one()
        assert failed_version.documents_generation is not None
        assert failure.payload_json == {
            "source_code": "documents-isolation",
            "raw_record_id": str(raw_ids["first-bad"]),
            "documents_generation": str(failed_version.documents_generation),
        }


@pytest.mark.asyncio
async def test_document_reconciliation_skips_terminal_and_not_due_failures(
    worker_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, raw_ids = await _seed_versions(
        worker_session_factory, "documents-eligibility", ["terminal", "not-due", "eligible"]
    )
    now = datetime.now(UTC)
    async with worker_session_factory() as setup:
        for record_id, dead_lettered, retry_at in (
            ("terminal", True, None),
            ("not-due", False, now + timedelta(hours=1)),
        ):
            stable_key = job_key(
                "parse_documents",
                "documents-eligibility",
                {"raw_record_id": str(raw_ids[record_id])},
            )
            setup.add(
                JobFailure(
                    job_type="parse_documents",
                    job_key=stable_key,
                    attempts=3 if dead_lettered else 1,
                    error_class="Synthetic",
                    error_message="Synthetic",
                    payload_json={
                        "source_code": "documents-eligibility",
                        "raw_record_id": str(raw_ids[record_id]),
                    },
                    dead_lettered=dead_lettered,
                    next_retry_at=retry_at,
                )
            )
        await setup.commit()
    adapter = DocumentAdapter()
    monkeypatch.setattr(
        "app.workers.jobs.source_adapters", lambda: {"documents-eligibility": adapter}
    )

    result = await reconcile_pending_documents(
        {
            "session_factory": worker_session_factory,
            "attachment_storage_path": tmp_path,
        }
    )

    assert result == {"processed": 1, "failed": 0}
    assert adapter.calls == ["eligible"]


@pytest.mark.asyncio
async def test_document_transient_retry_recovers_and_clears_failure_state(
    worker_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, raw_ids = await _seed_versions(worker_session_factory, "documents-recovery", ["recovering"])
    adapter = TransientDocumentAdapter(failures=1)
    monkeypatch.setattr("app.workers.jobs.source_adapters", lambda: {"documents-recovery": adapter})
    ctx = {
        "session_factory": worker_session_factory,
        "attachment_storage_path": tmp_path,
    }

    assert await reconcile_pending_documents(ctx) == {"processed": 0, "failed": 1}
    assert await reconcile_pending_documents(ctx) == {"processed": 0, "failed": 0}
    stable_key = job_key(
        "parse_documents",
        "documents-recovery",
        {"raw_record_id": str(raw_ids["recovering"])},
    )
    async with worker_session_factory() as advance:
        failure = await advance.scalar(select(JobFailure).where(JobFailure.job_key == stable_key))
        assert failure is not None and failure.attempts == 1
        failure.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        await advance.commit()

    assert await reconcile_pending_documents(ctx) == {"processed": 1, "failed": 0}
    async with worker_session_factory() as verify:
        failure = await verify.scalar(select(JobFailure).where(JobFailure.job_key == stable_key))
        assert failure is not None
        assert failure.attempts == 0
        assert failure.dead_lettered is False
        assert failure.next_retry_at is None


@pytest.mark.asyncio
async def test_document_transient_retry_stops_after_max_attempts(
    worker_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, raw_ids = await _seed_versions(worker_session_factory, "documents-exhausted", ["exhausted"])
    adapter = TransientDocumentAdapter(failures=10)
    monkeypatch.setattr(
        "app.workers.jobs.source_adapters", lambda: {"documents-exhausted": adapter}
    )
    ctx = {
        "session_factory": worker_session_factory,
        "attachment_storage_path": tmp_path,
    }
    stable_key = job_key(
        "parse_documents",
        "documents-exhausted",
        {"raw_record_id": str(raw_ids["exhausted"])},
    )
    for attempt in range(3):
        assert await reconcile_pending_documents(ctx) == {"processed": 0, "failed": 1}
        if attempt < 2:
            async with worker_session_factory() as advance:
                failure = await advance.scalar(
                    select(JobFailure).where(JobFailure.job_key == stable_key)
                )
                assert failure is not None
                failure.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
                await advance.commit()

    assert await reconcile_pending_documents(ctx) == {"processed": 0, "failed": 0}
    assert adapter.calls == ["exhausted", "exhausted", "exhausted"]
    async with worker_session_factory() as verify:
        failure = await verify.scalar(select(JobFailure).where(JobFailure.job_key == stable_key))
        assert failure is not None
        assert failure.attempts == 3
        assert failure.dead_lettered is True
        assert failure.next_retry_at is None
