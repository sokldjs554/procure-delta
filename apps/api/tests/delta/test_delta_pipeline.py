from __future__ import annotations

import importlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    Attachment,
    DocumentParse,
    JobFailure,
    Opportunity,
    OpportunityDelta,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
    StructuredExtraction,
)
from app.repositories.opportunities import upsert_opportunity_version
from app.services.normalize import normalize_raw_record
from app.sources.mock import MockSourceAdapter
from app.workers.extraction import reconcile_pending_extractions
from app.workers.jobs import reconcile_pending_documents


def worker() -> Any:
    assert importlib.util.find_spec("app.workers.delta") is not None, "delta worker missing"
    return importlib.import_module("app.workers.delta")


@pytest_asyncio.fixture
async def source(worker_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[UUID]:
    async with worker_session_factory() as session:
        row = SourceRegistry(
            code=f"delta-test-{uuid4()}",
            display_name="Synthetic delta test",
            base_url="https://example.invalid",
        )
        session.add(row)
        await session.commit()
        source_id = row.id
    yield source_id
    async with worker_session_factory() as session:
        raw_ids = list(
            await session.scalars(select(RawRecord.id).where(RawRecord.source_id == source_id))
        )
        versions = list(
            await session.scalars(
                select(OpportunityVersion).where(OpportunityVersion.raw_record_id.in_(raw_ids))
            )
        )
        version_ids = [row.id for row in versions]
        opportunity_ids = [row.opportunity_id for row in versions]
        attachment_ids = select(Attachment.id).where(
            Attachment.opportunity_version_id.in_(version_ids)
        )
        await session.execute(
            delete(JobFailure).where(
                (JobFailure.payload_json["to_version_id"].astext.in_([str(v) for v in version_ids]))
                | (JobFailure.payload_json["version_id"].astext.in_([str(v) for v in version_ids]))
                | (JobFailure.payload_json["raw_record_id"].astext.in_([str(v) for v in raw_ids]))
            )
        )
        await session.execute(
            delete(OpportunityDelta).where(OpportunityDelta.opportunity_id.in_(opportunity_ids))
        )
        await session.execute(
            delete(StructuredExtraction).where(
                StructuredExtraction.opportunity_version_id.in_(version_ids)
            )
        )
        await session.execute(
            delete(DocumentParse).where(DocumentParse.attachment_id.in_(attachment_ids))
        )
        await session.execute(
            delete(Attachment).where(Attachment.opportunity_version_id.in_(version_ids))
        )
        await session.execute(
            update(Opportunity)
            .where(Opportunity.id.in_(opportunity_ids))
            .values(current_version_id=None)
        )
        await session.execute(
            update(RawRecord).where(RawRecord.id.in_(raw_ids)).values(normalized_version_id=None)
        )
        await session.execute(
            delete(OpportunityVersion).where(OpportunityVersion.id.in_(version_ids))
        )
        await session.execute(delete(Opportunity).where(Opportunity.id.in_(opportunity_ids)))
        await session.execute(delete(RawRecord).where(RawRecord.id.in_(raw_ids)))
        await session.execute(delete(SourceRegistry).where(SourceRegistry.id == source_id))
        await session.commit()


async def add_version(
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    day: int,
    amount: str,
    *,
    complete: bool = True,
) -> UUID:
    async with factory() as session:
        raw = RawRecord(
            source_id=source_id,
            source_record_id="synthetic-delta",
            source_updated_at=datetime(2026, 9, day, tzinfo=UTC),
            payload_sha256=uuid4().hex * 2,
            payload_json={
                "title": "Synthetic delta",
                "buyer_name": "Synthetic buyer",
                "lifecycle_stage": "amendment",
                "estimated_amount": amount,
                "currency": "KRW",
                "is_synthetic": True,
            },
        )
        session.add(raw)
        await session.flush()
        result = await upsert_opportunity_version(session, raw, normalize_raw_record(raw))
        version = await session.get_one(OpportunityVersion, result.version_id)
        if complete:
            version.documents_discovered_at = datetime.now(UTC)
            version.documents_completed_at = datetime.now(UTC)
        await session.commit()
        return result.version_id


@pytest.mark.asyncio
async def test_actual_current_transition_survives_equivalent_watermark_and_late_arrival(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
) -> None:
    service = worker()
    first = await add_version(worker_session_factory, source, 1, "100")
    equivalent = await add_version(worker_session_factory, source, 20, "100")
    late = await add_version(worker_session_factory, source, 15, "120")
    current = await add_version(worker_session_factory, source, 25, "150")
    assert equivalent == first
    async with worker_session_factory() as session:
        historical = await session.get_one(OpportunityVersion, late)
        latest = await session.get_one(OpportunityVersion, current)
        assert historical.transition_kind == "historical"
        assert latest.previous_current_version_id == first
        assert latest.transition_kind == "current"
        assert latest.transition_at >= latest.created_at
    ctx = {"session_factory": worker_session_factory}
    await service.reconcile_pending_deltas(ctx)
    await service.reconcile_pending_deltas(ctx)
    async with worker_session_factory() as session:
        rows = list(
            await session.scalars(
                select(OpportunityDelta).where(OpportunityDelta.to_version_id.in_([late, current]))
            )
        )
        assert len(rows) == 2
        delta = next(row for row in rows if row.to_version_id == current)
        assert delta.from_version_id == first
        assert delta.field_changes_json["budget"]["before"]["estimated_amount"] == "100"
        assert delta.comparison_kind == "current_transition"
        assert (
            next(row for row in rows if row.to_version_id == late).comparison_kind == "historical"
        )
        selector = importlib.import_module("app.delta.service").latest_applicable_deltas
        selected = await selector(session, delta.opportunity_id)
        assert [row.id for row in selected] == [delta.id]


@pytest.mark.asyncio
async def test_no_delta_before_documents_complete_and_repair_appends_revision(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
) -> None:
    service = worker()
    first = await add_version(worker_session_factory, source, 1, "100")
    second = await add_version(worker_session_factory, source, 2, "120", complete=False)
    ctx = {"session_factory": worker_session_factory}
    assert (await service.compute_opportunity_delta(ctx, str(second)))["status"] == "pending"
    async with worker_session_factory() as session:
        row = await session.get_one(OpportunityVersion, second)
        row.documents_discovered_at = datetime.now(UTC)
        row.documents_completed_at = datetime.now(UTC)
        await session.commit()
    assert (await service.compute_opportunity_delta(ctx, str(second)))["status"] == "created"
    async with worker_session_factory() as session:
        original = (
            await session.scalars(
                select(OpportunityDelta).where(OpportunityDelta.to_version_id == second)
            )
        ).one()
        original_id, original_changes = original.id, original.document_changes_json
        session.add(
            Attachment(
                opportunity_version_id=second,
                source_url="https://example.invalid/repaired",
                filename="repair.bin",
                sha256="a" * 64,
                download_status="unsupported",
            )
        )
        await session.commit()
    assert (await service.compute_opportunity_delta(ctx, str(second)))["status"] == "created"
    assert (await service.compute_opportunity_delta(ctx, str(second)))["status"] == "existing"
    async with worker_session_factory() as session:
        original = await session.get_one(OpportunityDelta, original_id)
        assert original.document_changes_json == original_changes
        rows = list(
            await session.scalars(
                select(OpportunityDelta).where(
                    OpportunityDelta.from_version_id == first,
                    OpportunityDelta.to_version_id == second,
                )
            )
        )
        assert len(rows) == 2
        selected = await importlib.import_module("app.delta.service").latest_applicable_deltas(
            session, original.opportunity_id
        )
        assert len(selected) == 1
        assert selected[0].id != original_id
        assert selected[0].input_provenance_json["after"]["gaps"]


@pytest.mark.asyncio
async def test_default_amendment_documents_extraction_and_delta_pipeline(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    service = worker()
    async with worker_session_factory() as session:
        for record in MockSourceAdapter._RECORDS[2:4]:
            raw = RawRecord(
                source_id=source,
                source_record_id=record.source_record_id,
                source_updated_at=record.source_updated_at,
                payload_json=record.raw_payload,
                payload_sha256=uuid4().hex * 2,
            )
            session.add(raw)
            await session.flush()
            await upsert_opportunity_version(session, raw, normalize_raw_record(raw))
        code = (await session.get_one(SourceRegistry, source)).code
        await session.commit()
    monkeypatch.setattr("app.workers.jobs.source_adapters", lambda: {code: MockSourceAdapter()})
    ctx = {"session_factory": worker_session_factory, "attachment_storage_path": tmp_path}
    await reconcile_pending_documents(ctx)
    await reconcile_pending_extractions(ctx)
    await service.reconcile_pending_deltas(ctx)
    async with worker_session_factory() as session:
        ids = (
            select(OpportunityVersion.id)
            .join(RawRecord, OpportunityVersion.raw_record_id == RawRecord.id)
            .where(RawRecord.source_id == source)
        )
        delta = (
            await session.scalars(
                select(OpportunityDelta).where(OpportunityDelta.to_version_id.in_(ids))
            )
        ).one()
        assert delta.field_changes_json["closes_at"]["before"] == "2026-10-02T09:00:00+00:00"
        assert delta.field_changes_json["closes_at"]["after"] == "2026-10-05T09:00:00+00:00"
        assert "deadline_later" in delta.impact_reasons_json["codes"]
        assert delta.impact_level == "high"
        assert "certification_added" in delta.impact_reasons_json["codes"]
        original_delta_id = delta.id
        original_input_fingerprint = delta.input_fingerprint
        original_generation = (
            await session.get_one(OpportunityVersion, delta.to_version_id)
        ).documents_generation
    await reconcile_pending_documents(ctx)
    await reconcile_pending_extractions(ctx)
    await service.reconcile_pending_deltas(ctx)
    async with worker_session_factory() as session:
        deltas = list(
            await session.scalars(
                select(OpportunityDelta).where(OpportunityDelta.to_version_id.in_(ids))
            )
        )
        assert [row.id for row in deltas] == [original_delta_id]
        assert deltas[0].input_fingerprint == original_input_fingerprint
        replayed = await session.get_one(OpportunityVersion, deltas[0].to_version_id)
        assert replayed.documents_generation != original_generation


@pytest.mark.asyncio
async def test_terminal_document_discovery_failure_allows_raw_delta_without_false_removal(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    first = await add_version(worker_session_factory, source, 1, "100")
    second = await add_version(worker_session_factory, source, 2, "120", complete=False)
    async with worker_session_factory() as session:
        code = (await session.get_one(SourceRegistry, source)).code
        session.add(
            Attachment(
                opportunity_version_id=first,
                source_url="https://example.invalid/existing",
                filename="spec.bin",
                sha256="a" * 64,
                download_status="unsupported",
            )
        )
        await session.commit()

    class FailedSource(MockSourceAdapter):
        async def fetch_attachments(self, record: Any) -> Any:
            raise ValueError("terminal attachment discovery failure")

    monkeypatch.setattr("app.workers.jobs.source_adapters", lambda: {code: FailedSource()})
    ctx = {"session_factory": worker_session_factory, "attachment_storage_path": tmp_path}
    await reconcile_pending_documents(ctx)
    result = await worker().compute_opportunity_delta(ctx, str(second))
    assert result["status"] == "created"
    async with worker_session_factory() as session:
        delta = await session.get_one(OpportunityDelta, UUID(result["delta_id"]))
        assert delta.document_changes_json == {}
        assert delta.field_changes_json["budget"]["after"]["estimated_amount"] == "120"
        assert delta.input_provenance_json["after"]["manifest_complete"] is False
        assert delta.input_provenance_json["after"]["gaps"]


@pytest.mark.asyncio
async def test_document_reprocessing_closes_gate_until_completed(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
) -> None:
    from app.documents.service import materialize_attachment_refs

    await add_version(worker_session_factory, source, 1, "100")
    second = await add_version(worker_session_factory, source, 2, "120")
    async with worker_session_factory() as session:
        await materialize_attachment_refs(session, opportunity_version_id=second, refs=[])
        await session.commit()
    result = await worker().compute_opportunity_delta(
        {"session_factory": worker_session_factory}, str(second)
    )
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_concurrent_workers_produce_one_durable_delta(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
) -> None:
    import asyncio

    await add_version(worker_session_factory, source, 1, "100")
    second = await add_version(worker_session_factory, source, 2, "120")
    ctx = {"session_factory": worker_session_factory}
    results = await asyncio.gather(
        *(worker().compute_opportunity_delta(ctx, str(second)) for _ in range(2))
    )
    assert sorted(result["status"] for result in results) == ["created", "existing"]
    assert len({result["delta_id"] for result in results}) == 1


@pytest.mark.asyncio
async def test_real_arq_reconciliation_creates_persisted_delta(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import signal

    from arq.connections import RedisSettings, create_pool
    from arq.worker import Worker

    await add_version(worker_session_factory, source, 1, "100")
    second = await add_version(worker_session_factory, source, 2, "120")
    queue = f"arq:delta-test:{uuid4().hex}"
    monkeypatch.setattr(worker(), "WORKER_QUEUE", queue)
    redis = await create_pool(
        RedisSettings.from_dsn(os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")),
        default_queue_name=queue,
    )
    runner = Worker(
        [worker().compute_opportunity_delta],
        redis_pool=redis,
        queue_name=queue,
        burst=True,
        handle_signals=False,
        ctx={"session_factory": worker_session_factory},
    )
    try:
        outcome = await worker().reconcile_pending_deltas(
            {"session_factory": worker_session_factory, "redis": redis}
        )
        assert outcome["queued"] >= 1
        await runner.async_run()
        async with worker_session_factory() as session:
            delta = (
                await session.scalars(
                    select(OpportunityDelta).where(OpportunityDelta.to_version_id == second)
                )
            ).one()
            assert delta.impact_reasons_json["codes"] == ["budget_increased"]
    finally:
        from app.workers.jobs import job_key

        stable_key = job_key("compute_opportunity_delta", "version", {"to_version_id": str(second)})
        await redis.delete(queue, f"arq:result:{stable_key}", f"{queue}:health-check")
        if hasattr(signal, "SIGUSR1"):
            await runner.close()
        await redis.aclose()


@pytest.mark.asyncio
async def test_only_validated_nonconflicting_extraction_claims_enter_final_delta(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
) -> None:
    from app.extraction.deterministic import DeterministicExtractor
    from app.extraction.service import persist_extraction

    first = await add_version(worker_session_factory, source, 1, "100")
    second = await add_version(worker_session_factory, source, 2, "120")
    async with worker_session_factory() as session:
        for index, version_id in enumerate((first, second)):
            text = (
                "Title: Synthetic delta\nBuyer: Synthetic buyer\nCategory: IT services\n"
                "Budget: KRW 999\nCertifications: ISO 27001\n"
                f"Capabilities: {'Python' if index == 0 else 'Rust'}\n"
                "Participation constraints: Synthetic registered SMEs only"
            )
            attachment = Attachment(
                opportunity_version_id=version_id,
                source_url="https://example.invalid/spec",
                filename="spec.txt",
                sha256=str(index + 1) * 64,
                download_status="parsed",
            )
            session.add(attachment)
            await session.flush()
            session.add(
                DocumentParse(
                    attachment_id=attachment.id,
                    parser_kind="html",
                    parser_version="test-v1",
                    extracted_text=text,
                    status="trusted",
                    text_sha256="a" * 64,
                    quality_json={
                        "pages": [
                            {"page_number": 1, "text": text, "quality": {"status": "trusted"}}
                        ]
                    },
                )
            )
        await session.commit()
    ctx = {"session_factory": worker_session_factory}
    assert (await worker().compute_opportunity_delta(ctx, str(second)))["status"] == "pending"
    async with worker_session_factory() as session:
        for version_id in (first, second):
            row = await persist_extraction(session, version_id, DeterministicExtractor())
            assert row is not None and row.validation_status == "validated"
        await session.commit()
    result = await worker().compute_opportunity_delta(ctx, str(second))
    assert result["status"] == "created"
    async with worker_session_factory() as session:
        delta = await session.get_one(OpportunityDelta, UUID(result["delta_id"]))
        assert delta.field_changes_json["required_capabilities"]["before"] == ["Python"]
        assert delta.field_changes_json["required_capabilities"]["after"] == ["Rust"]
        assert delta.field_changes_json["required_capabilities"]["after_evidence"][0]["quote"] == (
            "Capabilities: Rust"
        )
        assert delta.field_changes_json["budget"]["after"]["estimated_amount"] == "120"
        extraction = (
            await session.scalars(
                select(StructuredExtraction).where(
                    StructuredExtraction.opportunity_version_id == second
                )
            )
        ).one()
        extraction.validation_status = "rejected"
        await session.commit()
    repaired = await worker().compute_opportunity_delta(ctx, str(second))
    async with worker_session_factory() as session:
        delta = await session.get_one(OpportunityDelta, UUID(repaired["delta_id"]))
        assert delta.field_changes_json["required_capabilities"]["after"] is None
        assert "capability_removed" not in delta.impact_reasons_json["codes"]
        assert delta.input_provenance_json["after"]["extraction_status"] == "rejected"


@pytest.mark.asyncio
async def test_gate_reloads_completion_after_concurrent_repair_starts(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.delta.service as delta_service

    await add_version(worker_session_factory, source, 1, "100")
    second = await add_version(worker_session_factory, source, 2, "120")
    original = delta_service.prepare_snapshot

    async def begin_repair_before_snapshot(session: Any, version: Any, extractor: Any) -> Any:
        if version.id == second:
            async with worker_session_factory() as repair:
                await repair.execute(
                    update(OpportunityVersion)
                    .where(OpportunityVersion.id == second)
                    .values(documents_completed_at=None)
                )
                await repair.commit()
        return await original(session, version, extractor)

    monkeypatch.setattr(delta_service, "prepare_snapshot", begin_repair_before_snapshot)
    result = await worker().compute_opportunity_delta(
        {"session_factory": worker_session_factory}, str(second)
    )
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_older_ocr_completion_cannot_finish_newer_document_processing(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
    tmp_path: Any,
) -> None:
    import asyncio

    from app.documents.ocr import OcrDocument, OcrResult
    from app.documents.service import persist_and_parse_attachments
    from app.sources.base import AttachmentRef

    await add_version(worker_session_factory, source, 1, "100")
    second = await add_version(worker_session_factory, source, 2, "120", complete=False)

    class PausedUnavailableOcr:
        provider = "synthetic-paused-test"
        provider_version = "v1"

        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def recognize(self, document: OcrDocument) -> OcrResult:
            self.entered.set()
            await self.release.wait()
            return OcrResult(
                provider=self.provider,
                provider_version=self.provider_version,
                synthetic=True,
                pages=(),
                extracted_text="",
                text_sha256=None,
                status="unavailable",
            )

    older, newer = PausedUnavailableOcr(), PausedUnavailableOcr()
    original = AttachmentRef(
        attachment_id="original",
        filename="original.pdf",
        url="https://example.invalid/original.pdf",
        media_type="application/pdf",
        fixture_key="synthetic-scanned-specification.pdf",
    )
    added = original.model_copy(
        update={
            "attachment_id": "added",
            "filename": "added.pdf",
            "url": "https://example.invalid/added.pdf",
        }
    )

    async def run(refs: list[AttachmentRef], adapter: PausedUnavailableOcr) -> None:
        async with worker_session_factory() as session:
            await persist_and_parse_attachments(
                session,
                opportunity_version_id=second,
                refs=refs,
                allowed_source_host="example.invalid",
                storage_root=tmp_path,
                ocr_adapter=adapter,
            )
            await session.commit()

    old_task = asyncio.create_task(run([original], older))
    new_task = None
    ctx = {"session_factory": worker_session_factory}
    try:
        await asyncio.wait_for(older.entered.wait(), timeout=5)
        new_task = asyncio.create_task(run([added, original], newer))
        await asyncio.wait_for(newer.entered.wait(), timeout=5)
        older.release.set()
        await asyncio.wait_for(old_task, timeout=5)
        # The newer worker has committed its native parse and is still awaiting OCR.
        result = await worker().compute_opportunity_delta(ctx, str(second))
        assert result["status"] == "pending"
        newer.release.set()
        await asyncio.wait_for(new_task, timeout=5)
        assert (await worker().compute_opportunity_delta(ctx, str(second)))["status"] == "created"
    finally:
        older.release.set()
        newer.release.set()
        await asyncio.gather(old_task, *([new_task] if new_task else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_stale_terminal_document_failure_does_not_block_newer_generation_recovery(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.documents.service import materialize_attachment_refs
    from app.workers.jobs import job_key

    await add_version(worker_session_factory, source, 1, "100")
    second = await add_version(worker_session_factory, source, 2, "120", complete=False)
    async with worker_session_factory() as session:
        await materialize_attachment_refs(session, opportunity_version_id=second, refs=[])
        version = await session.get_one(OpportunityVersion, second)
        old_generation = str(version.documents_generation)
        raw_id = str(version.raw_record_id)
        code = (await session.get_one(SourceRegistry, source)).code
        await session.commit()
        await materialize_attachment_refs(session, opportunity_version_id=second, refs=[])
        session.add(
            JobFailure(
                job_type="parse_documents",
                job_key=job_key("parse_documents", code, {"raw_record_id": raw_id}),
                attempts=3,
                error_class="ValueError",
                error_message="Synthetic old failure",
                dead_lettered=True,
                payload_json={"raw_record_id": raw_id, "documents_generation": old_generation},
            )
        )
        await session.commit()
    ctx = {"session_factory": worker_session_factory}
    assert (await worker().compute_opportunity_delta(ctx, str(second)))["status"] == "pending"

    class EmptySource(MockSourceAdapter):
        async def fetch_attachments(self, record: Any) -> Any:
            return []

    monkeypatch.setattr("app.workers.jobs.source_adapters", lambda: {code: EmptySource()})
    await reconcile_pending_documents(ctx)
    assert (await worker().compute_opportunity_delta(ctx, str(second)))["status"] == "created"
    async with worker_session_factory() as session:
        failure = (
            await session.scalars(
                select(JobFailure).where(
                    JobFailure.job_key
                    == job_key("parse_documents", code, {"raw_record_id": raw_id})
                )
            )
        ).one()
        assert failure.attempts == 0
        assert failure.dead_lettered is False


@pytest.mark.asyncio
async def test_new_document_generation_starts_its_own_bounded_attempts(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import timedelta

    import httpx

    from app.documents.service import materialize_attachment_refs
    from app.workers.jobs import job_key

    second = await add_version(worker_session_factory, source, 2, "120", complete=False)
    async with worker_session_factory() as session:
        await materialize_attachment_refs(session, opportunity_version_id=second, refs=[])
        version = await session.get_one(OpportunityVersion, second)
        raw_id = str(version.raw_record_id)
        old_generation = str(version.documents_generation)
        code = (await session.get_one(SourceRegistry, source)).code
        stable_key = job_key("parse_documents", code, {"raw_record_id": raw_id})
        await session.commit()
        await materialize_attachment_refs(session, opportunity_version_id=second, refs=[])
        session.add(
            JobFailure(
                job_type="parse_documents",
                job_key=stable_key,
                attempts=3,
                error_class="Synthetic",
                error_message="Old terminal error",
                dead_lettered=True,
                payload_json={"raw_record_id": raw_id, "documents_generation": old_generation},
            )
        )
        await session.commit()

    class FailingSource(MockSourceAdapter):
        async def fetch_attachments(self, record: Any) -> Any:
            raise httpx.ConnectTimeout("Synthetic temporary discovery failure")

    monkeypatch.setattr("app.workers.jobs.source_adapters", lambda: {code: FailingSource()})
    ctx = {"session_factory": worker_session_factory}
    for attempt in (1, 2, 3):
        assert (await reconcile_pending_documents(ctx))["failed"] == 1
        async with worker_session_factory() as session:
            failure = (
                await session.scalars(select(JobFailure).where(JobFailure.job_key == stable_key))
            ).one()
            assert failure.attempts == attempt
            assert failure.dead_lettered is (attempt == 3)
            if attempt < 3:
                failure.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()
    assert (await reconcile_pending_documents(ctx))["failed"] == 0


@pytest.mark.asyncio
async def test_retried_ocr_keeps_generation_and_exhausts_attempt_budget(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    from datetime import timedelta

    import httpx

    from app.documents.ocr import OcrDocument, OcrResult
    from app.sources.base import AttachmentRef
    from app.workers.jobs import job_key

    version_id = await add_version(worker_session_factory, source, 1, "100", complete=False)
    ref = AttachmentRef(
        attachment_id="scan",
        filename="scan.pdf",
        url="https://example.invalid/scan.pdf",
        media_type="application/pdf",
        fixture_key="synthetic-scanned-specification.pdf",
    )

    class ScannedSource(MockSourceAdapter):
        async def fetch_attachments(self, record: Any) -> Any:
            return [ref]

    class UnavailableProvider:
        provider = "synthetic-timeout"
        provider_version = "v1"
        calls = 0

        async def recognize(self, document: OcrDocument) -> OcrResult:
            self.calls += 1
            raise httpx.ConnectTimeout("Synthetic OCR timeout")

    async with worker_session_factory() as session:
        code = (await session.get_one(SourceRegistry, source)).code
        version = await session.get_one(OpportunityVersion, version_id)
        stable_key = job_key("parse_documents", code, {"raw_record_id": str(version.raw_record_id)})
    monkeypatch.setattr("app.workers.jobs.source_adapters", lambda: {code: ScannedSource()})
    provider = UnavailableProvider()
    ctx = {
        "session_factory": worker_session_factory,
        "attachment_storage_path": tmp_path,
        "ocr_adapter": provider,
    }
    generation = None
    for attempt in (1, 2, 3):
        assert (await reconcile_pending_documents(ctx))["failed"] == 1
        async with worker_session_factory() as session:
            failure = (
                await session.scalars(select(JobFailure).where(JobFailure.job_key == stable_key))
            ).one()
            version = await session.get_one(OpportunityVersion, version_id)
            if generation is None:
                generation = version.documents_generation
            assert generation is not None and version.documents_generation == generation
            assert failure.attempts == attempt
            assert failure.dead_lettered is (attempt == 3)
            if attempt < 3:
                failure.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()
    assert (await reconcile_pending_documents(ctx))["failed"] == 0
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_older_failing_ocr_worker_cannot_overwrite_newer_generation_failure(
    worker_session_factory: async_sessionmaker[AsyncSession],
    source: UUID,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    import asyncio

    import httpx

    from app.documents.ocr import OcrDocument, OcrResult
    from app.documents.service import materialize_attachment_refs
    from app.sources.base import AttachmentRef
    from app.workers.jobs import job_key

    version_id = await add_version(worker_session_factory, source, 1, "100", complete=False)
    ref = AttachmentRef(
        attachment_id="scan",
        filename="scan.pdf",
        url="https://example.invalid/scan.pdf",
        media_type="application/pdf",
        fixture_key="synthetic-scanned-specification.pdf",
    )

    class ScannedSource(MockSourceAdapter):
        async def fetch_attachments(self, record: Any) -> Any:
            return [ref]

    class PausedFailure:
        provider = "synthetic-paused-failure"
        provider_version = "v1"

        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def recognize(self, document: OcrDocument) -> OcrResult:
            self.entered.set()
            await self.release.wait()
            raise httpx.ConnectTimeout("Synthetic older worker error")

    async with worker_session_factory() as session:
        code = (await session.get_one(SourceRegistry, source)).code
        raw_id = str((await session.get_one(OpportunityVersion, version_id)).raw_record_id)
    stable_key = job_key("parse_documents", code, {"raw_record_id": raw_id})
    monkeypatch.setattr("app.workers.jobs.source_adapters", lambda: {code: ScannedSource()})
    provider = PausedFailure()
    task = asyncio.create_task(
        reconcile_pending_documents(
            {
                "session_factory": worker_session_factory,
                "attachment_storage_path": tmp_path,
                "ocr_adapter": provider,
            }
        )
    )
    try:
        await asyncio.wait_for(provider.entered.wait(), timeout=5)
        async with worker_session_factory() as session:
            await materialize_attachment_refs(
                session, opportunity_version_id=version_id, refs=[ref]
            )
            generation = (
                await session.get_one(OpportunityVersion, version_id)
            ).documents_generation
            session.add(
                JobFailure(
                    job_type="parse_documents",
                    job_key=stable_key,
                    attempts=1,
                    error_class="NewerFailure",
                    error_message="Newer state",
                    dead_lettered=False,
                    next_retry_at=datetime.now(UTC),
                    payload_json={"raw_record_id": raw_id, "documents_generation": str(generation)},
                )
            )
            await session.commit()
        provider.release.set()
        await asyncio.wait_for(task, timeout=5)
        async with worker_session_factory() as session:
            failure = (
                await session.scalars(select(JobFailure).where(JobFailure.job_key == stable_key))
            ).one()
            assert failure.attempts == 1
            assert failure.error_class == "NewerFailure"
            assert failure.payload_json["documents_generation"] == str(generation)
            assert (
                await session.get_one(OpportunityVersion, version_id)
            ).documents_completed_at is None
    finally:
        provider.release.set()
        await asyncio.gather(task, return_exceptions=True)
