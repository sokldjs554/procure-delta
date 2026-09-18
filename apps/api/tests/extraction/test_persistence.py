import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.documents.service import persist_and_parse_attachments
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.schemas import ExtractionResult
from app.extraction.service import (
    build_document_bundle,
    persist_extraction,
    trusted_extraction_view,
)
from app.models import (
    Attachment,
    DocumentParse,
    JobFailure,
    Opportunity,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
    StructuredExtraction,
)
from app.sources.mock import MockSourceAdapter
from app.workers.extraction import extract_version, reconcile_pending_extractions


@pytest_asyncio.fixture
async def seeded(worker_session_factory, tmp_path):
    code = "extract-" + uuid4().hex
    async with worker_session_factory() as session:
        source = SourceRegistry(
            code=code, display_name="Synthetic", base_url="https://example.invalid"
        )
        session.add(source)
        await session.flush()
        source_id = source.id
        raw = RawRecord(
            source_id=source_id,
            source_record_id="synthetic-pre-spec-001",
            payload_json={},
            payload_sha256="a" * 64,
            normalization_status="normalized",
        )
        opportunity = Opportunity(canonical_key=code, title="Upstream title", buyer_name="Buyer")
        session.add_all([raw, opportunity])
        await session.flush()
        version = OpportunityVersion(
            opportunity_id=opportunity.id,
            raw_record_id=raw.id,
            version_number=1,
            source_record_id=raw.source_record_id,
            normalized_json={"title": "Upstream title", "estimated_amount": "125000000"},
            normalized_sha256="b" * 64,
        )
        session.add(version)
        await session.flush()
        version_id, raw_id, opportunity_id = version.id, raw.id, opportunity.id
        await session.commit()
        adapter = MockSourceAdapter()
        record = await adapter.fetch_record("synthetic-pre-spec-001")
        await persist_and_parse_attachments(
            session,
            opportunity_version_id=version_id,
            refs=await adapter.fetch_attachments(record),
            allowed_source_host="example.invalid",
            storage_root=tmp_path,
        )
        await session.commit()
    yield version_id
    async with worker_session_factory() as session:
        await session.execute(
            delete(JobFailure).where(
                JobFailure.payload_json["version_id"].astext == str(version_id)
            )
        )
        await session.execute(
            delete(StructuredExtraction).where(
                StructuredExtraction.opportunity_version_id == version_id
            )
        )
        ids = select(Attachment.id).where(Attachment.opportunity_version_id == version_id)
        await session.execute(delete(DocumentParse).where(DocumentParse.attachment_id.in_(ids)))
        await session.execute(
            delete(Attachment).where(Attachment.opportunity_version_id == version_id)
        )
        await session.execute(delete(OpportunityVersion).where(OpportunityVersion.id == version_id))
        await session.execute(delete(RawRecord).where(RawRecord.id == raw_id))
        await session.execute(delete(Opportunity).where(Opportunity.id == opportunity_id))
        await session.execute(delete(SourceRegistry).where(SourceRegistry.id == source_id))
        await session.commit()


@pytest.mark.asyncio
async def test_real_stored_ocr_bundle_and_conflict_view_preserve_history(
    seeded, worker_session_factory
):
    async with worker_session_factory() as session:
        version = await session.get_one(OpportunityVersion, seeded)
        original = deepcopy(version.normalized_json)
        bundle = await build_document_bundle(session, seeded)
        assert any(page.parser_kind == "ocr" for page in bundle.pages)
        assert not any(page.parser_kind == "native_pdf" and not page.text for page in bundle.pages)
        result = await persist_extraction(session, seeded, DeterministicExtractor())
        await session.commit()
        assert result.validation_status == "validated"
        assert result.latency_ms >= 0 and result.prompt_tokens is None
        assert result.input_fingerprint == bundle.fingerprint
        view = await trusted_extraction_view(session, result.id)
        assert "title" not in view.fields
        assert view.conflicts["title"]["upstream"] == "Upstream title"
        assert view.fields["estimated_amount"] == "125000000"
        assert view.fields["required_capabilities"]
        await session.refresh(version)
        assert version.normalized_json == original


@pytest.mark.asyncio
async def test_concurrent_and_replayed_jobs_make_one_call(seeded, worker_session_factory):
    class Spy(DeterministicExtractor):
        calls = 0

        async def extract(self, document):
            self.calls += 1
            await asyncio.sleep(0.02)
            return await super().extract(document)

    spy = Spy()

    async def run():
        async with worker_session_factory() as session:
            result = await persist_extraction(session, seeded, spy)
            await session.commit()
            return result.id

    identifiers = await asyncio.gather(run(), run())
    identifiers.append(await run())
    assert len(set(identifiers)) == 1 and spy.calls == 1


@pytest.mark.asyncio
async def test_rejected_result_is_durable_and_never_trusted(seeded, worker_session_factory):
    class Invalid(DeterministicExtractor):
        async def extract(self, document):
            return ExtractionResult(output={"title": "invented"})

    async with worker_session_factory() as session:
        result = await persist_extraction(session, seeded, Invalid())
        await session.commit()
        assert result.validation_status == "rejected"
        assert result.output_json == {"title": "invented"}
        assert result.validation_errors_json["errors"]
        assert await trusted_extraction_view(session, result.id) is None


@pytest.mark.asyncio
async def test_worker_reconciliation_replays_and_new_inputs_have_new_identity(
    seeded, worker_session_factory
):
    ctx = {"session_factory": worker_session_factory}
    first = await extract_version(ctx, str(seeded))
    assert first["status"] == "validated"
    await reconcile_pending_extractions(ctx)
    async with worker_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(StructuredExtraction)
            .where(StructuredExtraction.opportunity_version_id == seeded)
        )
        assert count == 1
        row = await session.scalar(
            select(DocumentParse)
            .join(Attachment)
            .where(Attachment.opportunity_version_id == seeded, DocumentParse.parser_kind == "ocr")
        )
        row.status = "needs_ocr"
        await session.commit()
    second = await extract_version(ctx, str(seeded))
    assert second["job_key"] != first["job_key"]
    assert second["status"] == "rejected"


@pytest.mark.asyncio
async def test_actual_default_demo_has_useful_native_and_ocr_results(session, tmp_path):
    from app.workers.jobs import poll_source, reconcile_pending_documents

    ctx = {"session": session, "attachment_storage_path": tmp_path}
    for _ in range(3):
        await poll_source(ctx)
    await reconcile_pending_documents(ctx)
    await reconcile_pending_extractions(ctx)
    rows = list(await session.scalars(select(StructuredExtraction)))
    valid = [row for row in rows if row.validation_status == "validated"]
    assert any(
        any(page["parser_kind"] == "ocr" for page in row.input_bundle_json["pages"])
        for row in valid
    )
    assert any(
        all(page["parser_kind"] != "ocr" for page in row.input_bundle_json["pages"])
        and row.output_json.get("estimated_amount") == "125000000"
        for row in valid
    )
    assert any(row.validation_status == "rejected" for row in rows)


@pytest.mark.asyncio
async def test_worker_transient_recovery_and_dlq(seeded, worker_session_factory):
    from datetime import UTC, datetime, timedelta

    import httpx
    from arq import Retry

    class Unavailable(DeterministicExtractor):
        calls = 0
        recovering = False

        async def extract(self, document):
            self.calls += 1
            if not self.recovering:
                raise httpx.ConnectError("synthetic failure")
            return await super().extract(document)

    extractor = Unavailable()
    ctx = {"session_factory": worker_session_factory, "extractor": extractor}
    with pytest.raises(Retry):
        await extract_version(ctx, str(seeded))
    assert (await extract_version(ctx, str(seeded)))["status"] == "deferred"
    assert extractor.calls == 1
    async with worker_session_factory() as session:
        failure = await session.scalar(
            select(JobFailure).where(JobFailure.payload_json["version_id"].astext == str(seeded))
        )
        failure.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    extractor.recovering = True
    result = await reconcile_pending_extractions(ctx)
    assert result["processed"] == 1 and result["failed"] == 0
    async with worker_session_factory() as session:
        failure = await session.scalar(
            select(JobFailure).where(JobFailure.payload_json["version_id"].astext == str(seeded))
        )
        assert failure.attempts == 0 and failure.next_retry_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,attempts", [(401, 1), (503, 3)])
async def test_worker_failure_classification_and_bounded_retries(
    seeded, worker_session_factory, status, attempts
):
    from datetime import UTC, datetime, timedelta

    import httpx
    from arq import Retry

    class Failing(DeterministicExtractor):
        calls = 0

        async def extract(self, document):
            self.calls += 1
            request = httpx.Request("POST", "https://provider.invalid")
            raise httpx.HTTPStatusError(
                "failed", request=request, response=httpx.Response(status, request=request)
            )

    extractor = Failing()
    ctx = {"session_factory": worker_session_factory, "extractor": extractor}
    for index in range(attempts):
        if index < attempts - 1:
            with pytest.raises(Retry):
                await extract_version(ctx, str(seeded))
        else:
            assert (await extract_version(ctx, str(seeded)))["status"] == "dead_lettered"
        async with worker_session_factory() as session:
            failure = await session.scalar(
                select(JobFailure).where(
                    JobFailure.payload_json["version_id"].astext == str(seeded)
                )
            )
            if not failure.dead_lettered:
                failure.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
    assert (await reconcile_pending_extractions(ctx))["processed"] == 0
    assert extractor.calls == attempts


@pytest.mark.asyncio
async def test_restart_reconciler_enqueues_stable_worker_identity(seeded, worker_session_factory):
    from unittest.mock import AsyncMock

    from arq.connections import ArqRedis

    from app.workers.jobs import WORKER_QUEUE

    redis = AsyncMock(spec=ArqRedis)
    ctx = {"session_factory": worker_session_factory, "redis": redis}
    assert (await reconcile_pending_extractions(ctx))["queued"] == 1
    first = redis.enqueue_job.call_args
    assert first.args[:2] == ("extract_version", str(seeded))
    assert first.kwargs["_queue_name"] == WORKER_QUEUE
    await reconcile_pending_extractions(ctx)
    assert redis.enqueue_job.call_args == first


@pytest.mark.asyncio
async def test_invalid_hosted_json_is_persisted_rejected(seeded, worker_session_factory):
    import httpx

    from app.extraction.hosted import HostedExtractor
    from app.sources.http import ResilientHttpClient

    async with ResilientHttpClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="invalid provider JSON")
        )
    ) as client:
        extractor = HostedExtractor(
            endpoint="https://provider.invalid", provider="mock", model="1", client=client
        )
        async with worker_session_factory() as session:
            row = await persist_extraction(session, seeded, extractor)
            await session.commit()
            assert row.validation_status == "rejected"
            assert row.output_json["_invalid_json"] == "invalid provider JSON"
            assert await trusted_extraction_view(session, row.id) is None
