from __future__ import annotations

import os
import signal
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from arq import Retry
from arq.connections import RedisSettings, create_pool
from arq.worker import Worker
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.models import (
    IngestRun,
    JobFailure,
    Opportunity,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
)
from app.sources.base import DiscoveryPage
from app.workers.jobs import (
    _is_transient,
    _safe_error_message,
    ingest_record,
    job_key,
    poll_source,
    reconcile_pending_normalizations,
)


def _normalizable_payload(title: str = "Synthetic tender") -> dict[str, object]:
    return {
        "title": title,
        "buyer_name": "Synthetic buyer",
        "lifecycle_stage": "tender",
        "is_synthetic": True,
    }


@pytest.mark.asyncio
async def test_ingest_worker_commits_raw_before_creating_normalized_version(
    session: AsyncSession,
) -> None:
    source = SourceRegistry(
        code="mock-pipeline", display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    await session.commit()

    result = await ingest_record(
        {"session": session},
        source.code,
        {"source_record_id": "tender-1", "raw_payload": _normalizable_payload()},
    )

    raw = await session.scalar(select(RawRecord).where(RawRecord.source_id == source.id))
    assert result["status"] == "created"
    assert raw is not None
    assert raw.normalization_status == "normalized"
    assert raw.normalized_version_id is not None
    assert await session.scalar(select(Opportunity)) is not None
    assert await session.scalar(select(OpportunityVersion)) is not None


@pytest.mark.asyncio
async def test_normalization_failure_preserves_raw_and_is_durably_visible(
    worker_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_code = "mock-invalid"
    async with worker_session_factory() as setup:
        source = SourceRegistry(
            code=source_code, display_name="Mock", base_url="https://example.invalid"
        )
        setup.add(source)
        await setup.commit()
        source_id = source.id

    result = await ingest_record(
        {"session_factory": worker_session_factory},
        source_code,
        {"source_record_id": "invalid-1", "raw_payload": {"title": "Synthetic"}},
    )

    async with worker_session_factory() as verify:
        raw = await verify.scalar(select(RawRecord).where(RawRecord.source_id == source_id))
        failure = await verify.scalar(
            select(JobFailure).where(JobFailure.payload_json["source_code"].astext == source_code)
        )
        assert result["status"] == "dead_lettered"
        assert raw is not None
        assert raw.normalization_status == "failed"
        assert failure is not None and failure.dead_lettered is True
        assert (
            await verify.scalar(
                select(OpportunityVersion)
                .join(RawRecord, OpportunityVersion.raw_record_id == RawRecord.id)
                .where(RawRecord.source_id == source_id)
            )
            is None
        )


@pytest.mark.asyncio
async def test_reconciliation_processes_committed_pending_raw_records(
    worker_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with worker_session_factory() as setup:
        source = SourceRegistry(
            code="mock-reconcile", display_name="Mock", base_url="https://example.invalid"
        )
        setup.add(source)
        await setup.flush()
        raw = RawRecord(
            source_id=source.id,
            source_record_id="pending-1",
            payload_json=_normalizable_payload(),
            payload_sha256="9" * 64,
        )
        setup.add(raw)
        await setup.flush()
        normalization_key = job_key("normalize_record", "raw", {"raw_record_id": str(raw.id)})
        setup.add(
            JobFailure(
                job_type="normalize_record",
                job_key=normalization_key,
                attempts=2,
                error_class="OperationalError",
                error_message="OperationalError",
                payload_json={"raw_record_id": str(raw.id)},
                dead_lettered=False,
                next_retry_at=datetime.now(UTC),
            )
        )
        await setup.commit()
        raw_id = raw.id

    result = await reconcile_pending_normalizations({"session_factory": worker_session_factory})

    async with worker_session_factory() as verify:
        stored = await verify.get_one(RawRecord, raw_id)
        assert result == {"normalized": 1, "failed": 0}
        assert stored.normalization_status == "normalized"
        assert stored.normalized_version_id is not None
        recovered = await verify.scalar(
            select(JobFailure).where(JobFailure.job_key == normalization_key)
        )
        assert recovered is not None
        assert recovered.attempts == 0
        assert recovered.next_retry_at is None


@pytest.mark.asyncio
async def test_poll_continues_after_invalid_pending_raw_with_real_transactions(
    worker_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_code = "mock-mixed-pending"
    async with worker_session_factory() as setup:
        source = SourceRegistry(
            code=source_code, display_name="Mock", base_url="https://example.invalid"
        )
        setup.add(source)
        await setup.flush()
        setup.add_all(
            [
                RawRecord(
                    source_id=source.id,
                    source_record_id="legacy-invalid",
                    payload_json={"title": "Legacy sparse"},
                    payload_sha256="c" * 64,
                ),
                RawRecord(
                    source_id=source.id,
                    source_record_id="valid-after-invalid",
                    payload_json=_normalizable_payload("Valid after invalid"),
                    payload_sha256="d" * 64,
                ),
            ]
        )
        await setup.commit()
        source_id = source.id

    class EmptyAdapter:
        async def discover(self, _cursor: str | None) -> DiscoveryPage:
            return DiscoveryPage()

    monkeypatch.setattr("app.workers.jobs.source_adapters", lambda: {source_code: EmptyAdapter()})
    result = await poll_source({"session_factory": worker_session_factory}, source_code)

    async with worker_session_factory() as verify:
        records = (
            await verify.scalars(
                select(RawRecord)
                .where(RawRecord.source_id == source_id)
                .order_by(RawRecord.source_record_id)
            )
        ).all()
        run = await verify.scalar(select(IngestRun).where(IngestRun.source_id == source_id))
        assert result == {"status": "success", "source": source_code}
        assert [(record.source_record_id, record.normalization_status) for record in records] == [
            ("legacy-invalid", "failed"),
            ("valid-after-invalid", "normalized"),
        ]
        assert run is not None and run.failure_count == 1
        assert (
            await verify.scalar(select(JobFailure).where(JobFailure.job_type == "normalize_record"))
            is not None
        )


@pytest.mark.asyncio
async def test_reconciliation_clears_exhausted_ingest_failure_after_recovery(
    worker_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_code = "mock-normalize-recovery"
    async with worker_session_factory() as setup:
        setup.add(
            SourceRegistry(
                code=source_code, display_name="Mock", base_url="https://example.invalid"
            )
        )
        await setup.commit()

    async def unavailable(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("normalize", {}, OSError("synthetic connection loss"))

    monkeypatch.setattr("app.workers.jobs._normalize_persisted_raw", unavailable)
    payload = {
        "source_record_id": "recoverable-1",
        "raw_payload": _normalizable_payload("Recoverable tender"),
    }
    with pytest.raises(Retry):
        await ingest_record({"session_factory": worker_session_factory}, source_code, payload)
    with pytest.raises(Retry):
        await ingest_record({"session_factory": worker_session_factory}, source_code, payload)
    terminal = await ingest_record(
        {"session_factory": worker_session_factory}, source_code, payload
    )
    assert terminal["status"] == "dead_lettered"

    monkeypatch.undo()
    recovered = await reconcile_pending_normalizations({"session_factory": worker_session_factory})

    async with worker_session_factory() as verify:
        raw = await verify.scalar(
            select(RawRecord).where(RawRecord.source_record_id == "recoverable-1")
        )
        assert raw is not None
        failure = await verify.scalar(
            select(JobFailure).where(
                JobFailure.job_type == "ingest_record",
                JobFailure.payload_json["raw_record_id"].astext == str(raw.id),
            )
        )
        assert recovered["normalized"] >= 1
        assert raw.normalization_status == "normalized"
        assert failure is not None
        assert failure.attempts == 0
        assert failure.dead_lettered is False
        assert failure.next_retry_at is None


@pytest.mark.asyncio
async def test_reconciliation_restores_pending_raw_with_existing_version(
    worker_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_code = "mock-existing-version-recovery"
    payload = {
        "source_record_id": "existing-version-1",
        "raw_payload": _normalizable_payload("Existing version tender"),
    }
    async with worker_session_factory() as setup:
        setup.add(
            SourceRegistry(
                code=source_code, display_name="Mock", base_url="https://example.invalid"
            )
        )
        await setup.commit()

    created = await ingest_record(
        {"session_factory": worker_session_factory}, source_code, payload
    )
    assert created["status"] == "created"
    async with worker_session_factory() as damage:
        raw = await damage.scalar(
            select(RawRecord).where(RawRecord.source_record_id == "existing-version-1")
        )
        assert raw is not None and raw.normalized_version_id is not None
        version_id = raw.normalized_version_id
        raw.normalization_status = "pending"
        raw.normalized_at = None
        await damage.commit()

    result = await reconcile_pending_normalizations(
        {"session_factory": worker_session_factory}
    )

    async with worker_session_factory() as verify:
        raw = await verify.scalar(
            select(RawRecord).where(RawRecord.source_record_id == "existing-version-1")
        )
        assert result["normalized"] >= 1
        assert raw is not None
        assert raw.normalization_status == "normalized"
        assert raw.normalized_at is not None
        assert raw.normalized_version_id == version_id
        assert (
            await verify.scalar(
                select(func.count()).select_from(OpportunityVersion).where(
                    OpportunityVersion.id == version_id
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_poll_source_persists_discovered_raw_records(session: AsyncSession) -> None:
    source = SourceRegistry(
        code="mock",
        display_name="Mock",
        base_url="https://example.invalid",
        polling_interval_seconds=60,
    )
    session.add(source)
    await session.commit()

    result = await poll_source({"session": session}, "mock")

    assert result["status"] == "success"
    assert (
        len(
            (await session.scalars(select(RawRecord).where(RawRecord.source_id == source.id))).all()
        )
        == 2
    )


@pytest.mark.asyncio
async def test_malformed_job_is_dead_lettered_without_retry(session: AsyncSession) -> None:
    source = SourceRegistry(code="mock", display_name="Mock", base_url="https://example.invalid")
    session.add(source)
    await session.commit()

    result = await ingest_record(
        {"session": session}, "mock", {"source_record_id": "missing-payload"}
    )

    failure = await session.scalar(
        select(JobFailure).where(JobFailure.payload_json["source_code"].astext == "mock")
    )
    assert result["status"] == "dead_lettered"
    assert failure is not None
    assert failure.dead_lettered is True
    assert failure.attempts == 1


@pytest.mark.asyncio
async def test_unexpected_ingest_failure_is_terminal_with_original_replay_payload(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SourceRegistry(
        code="mock-unexpected", display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    await session.commit()

    async def fail_unexpectedly(*_args: object, **_kwargs: object) -> None:
        raise ValueError("synthetic programmer error")

    monkeypatch.setattr("app.workers.jobs.ingest_raw_record", fail_unexpectedly)
    payload = {
        "source_record_id": "notice-original",
        "raw_payload": {"title": "Synthetic", "nested": {"revision": 2}},
        "http_etag": '"v2"',
    }

    result = await ingest_record({"session": session}, "mock-unexpected", payload)

    failure = await session.scalar(
        select(JobFailure).where(JobFailure.payload_json["source_code"].astext == "mock-unexpected")
    )
    assert result["status"] == "dead_lettered"
    assert failure is not None
    assert failure.dead_lettered is True
    assert failure.next_retry_at is None
    assert failure.payload_json == {"source_code": "mock-unexpected", **payload}


@pytest.mark.asyncio
async def test_arq_worker_executes_enqueued_poll_and_persists_raw_records(
    session: AsyncSession, worker_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    queue_name = f"arq:task4:{uuid4().hex}"
    redis = await create_pool(
        RedisSettings.from_dsn(os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")),
        default_queue_name=queue_name,
    )
    try:
        job = await redis.enqueue_job("poll_source", "mock", _job_id=f"task4-{uuid4().hex}")
        assert job is not None
        worker = Worker(
            [poll_source],
            redis_pool=redis,
            queue_name=queue_name,
            burst=True,
            handle_signals=False,
            ctx={"session_factory": worker_session_factory},
        )

        await worker.async_run()

        assert await job.result(timeout=2) == {"status": "success", "source": "mock"}
        mock_source = await session.scalar(
            select(SourceRegistry).where(SourceRegistry.code == "mock")
        )
        assert mock_source is not None
        assert (
            len(
                (
                    await session.scalars(
                        select(RawRecord).where(RawRecord.source_id == mock_source.id)
                    )
                ).all()
            )
            == 2
        )
    finally:
        await redis.delete(queue_name)
        await redis.delete(f"arq:result:{job.job_id}")
        if hasattr(signal, "SIGUSR1"):
            await worker.close()
        await redis.aclose()


def test_failure_message_excludes_upstream_query_secrets() -> None:
    request = httpx.Request("GET", "https://example.test/notices?serviceKey=synthetic-secret")
    error = httpx.HTTPStatusError("upstream failed", request=request, response=httpx.Response(500))

    message = _safe_error_message(error)

    assert "synthetic-secret" not in message
    assert "serviceKey" not in message
    assert message == "HTTPStatusError(status=500)"


def test_generic_failure_message_excludes_network_url_secrets() -> None:
    error = httpx.ConnectError(
        "connect failed",
        request=httpx.Request("GET", "https://example.test/?token=synthetic-secret"),
    )

    assert _safe_error_message(error) == "ConnectError"


def test_database_retry_classification_only_allows_connection_serialization_or_deadlock() -> None:
    class DatabaseError(Exception):
        def __init__(self, sqlstate: str) -> None:
            self.sqlstate = sqlstate

    from sqlalchemy.exc import DBAPIError

    assert _is_transient(DBAPIError.instance(None, None, DatabaseError("40001"), Exception))
    assert _is_transient(DBAPIError.instance(None, None, DatabaseError("40P01"), Exception))
    assert not _is_transient(DBAPIError.instance(None, None, DatabaseError("23505"), Exception))


def test_connection_operational_error_without_sqlstate_is_transient() -> None:
    error = OperationalError("SELECT 1", {}, OSError("synthetic connection loss"))

    assert _is_transient(error)


@pytest.mark.asyncio
async def test_transient_failure_is_retried_then_success_clears_reconciliation_state(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SourceRegistry(
        code="mock-retry", display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    await session.commit()

    async def unavailable(*_args: object, **_kwargs: object) -> None:
        raise httpx.ConnectError("synthetic outage")

    monkeypatch.setattr("app.workers.jobs.ingest_raw_record", unavailable)
    payload = {"source_record_id": "notice-1", "raw_payload": _normalizable_payload()}

    with pytest.raises(Retry, match="defer"):
        await ingest_record({"session": session}, "mock-retry", payload)

    failure = await session.scalar(
        select(JobFailure).where(JobFailure.payload_json["source_code"].astext == "mock-retry")
    )
    assert failure is not None
    assert failure.attempts == 1
    assert failure.dead_lettered is False
    assert failure.next_retry_at is not None

    monkeypatch.undo()
    result = await ingest_record({"session": session}, "mock-retry", payload)
    await session.refresh(failure)

    assert result["status"] == "created"
    assert failure.next_retry_at is None


@pytest.mark.asyncio
async def test_upstream_outage_records_failure_while_health_and_raw_data_remain_available(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SourceRegistry(
        code="mock-outage", display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    await ingest_record(
        {"session": session},
        "mock-outage",
        {"source_record_id": "existing", "raw_payload": _normalizable_payload()},
    )

    class OutageAdapter:
        async def discover(self, _cursor: str | None) -> object:
            raise httpx.ConnectError("synthetic upstream outage")

    monkeypatch.setattr(
        "app.workers.jobs.source_adapters", lambda: {"mock-outage": OutageAdapter()}
    )
    with pytest.raises(Retry):
        await poll_source({"session": session}, "mock-outage")

    assert await session.scalar(select(RawRecord)) is not None
    assert await session.scalar(select(JobFailure)) is not None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/live")
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_disabled_source_skips_adapter_discovery(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SourceRegistry(
        code="mock-disabled",
        display_name="Disabled mock",
        base_url="https://example.invalid",
        enabled=False,
    )
    session.add(source)
    await session.commit()

    class AdapterThatMustNotDiscover:
        async def discover(self, _cursor: str | None) -> object:
            pytest.fail("disabled sources must not call adapter.discover")

    monkeypatch.setattr(
        "app.workers.jobs.source_adapters",
        lambda: {"mock-disabled": AdapterThatMustNotDiscover()},
    )

    result = await poll_source({"session": session}, "mock-disabled")

    assert result == {"status": "disabled", "source": "mock-disabled"}
    assert (
        await session.scalars(select(IngestRun).where(IngestRun.source_id == source.id))
    ).all() == []


@pytest.mark.asyncio
async def test_poll_failure_updates_its_captured_run_not_another_running_run(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SourceRegistry(
        code="mock-concurrent", display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    await session.commit()
    concurrent_run_id = None

    class ConcurrentFailureAdapter:
        async def discover(self, _cursor: str | None) -> object:
            nonlocal concurrent_run_id
            concurrent_run = IngestRun(source_id=source.id, status="running")
            session.add(concurrent_run)
            await session.commit()
            concurrent_run_id = concurrent_run.id
            raise ValueError("synthetic nontransient discovery failure")

    monkeypatch.setattr(
        "app.workers.jobs.source_adapters",
        lambda: {"mock-concurrent": ConcurrentFailureAdapter()},
    )

    result = await poll_source({"session": session}, "mock-concurrent")

    runs = (
        await session.scalars(
            select(IngestRun).where(IngestRun.source_id == source.id).order_by(IngestRun.started_at)
        )
    ).all()
    assert result["status"] == "dead_lettered"
    assert len(runs) == 2
    assert concurrent_run_id is not None
    own_run = next(run for run in runs if run.id != concurrent_run_id)
    concurrent_run = next(run for run in runs if run.id == concurrent_run_id)
    assert own_run.status == "failed"
    assert own_run.failure_count == 1
    assert own_run.finished_at is not None
    assert concurrent_run.status == "running"
    assert concurrent_run.failure_count == 0
    assert concurrent_run.finished_at is None


@pytest.mark.asyncio
async def test_successful_retry_clears_existing_dead_letter_and_retry_schedule(
    session: AsyncSession,
) -> None:
    source_code = "mock-recovered"
    source = SourceRegistry(
        code=source_code, display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    payload = {"source_record_id": "notice-1", "raw_payload": _normalizable_payload()}
    replay_payload = {"source_code": source_code, **payload}
    stable_key = job_key("ingest_record", source_code, replay_payload)
    failure = JobFailure(
        job_type="ingest_record",
        job_key=stable_key,
        attempts=3,
        error_class="ValueError",
        error_message="ValueError",
        payload_json=replay_payload,
        dead_lettered=True,
        next_retry_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    session.add(failure)
    await session.commit()

    result = await ingest_record({"session": session}, source_code, payload)
    await session.refresh(failure)

    assert result["status"] == "created"
    assert failure.attempts == 0
    assert failure.dead_lettered is False
    assert failure.next_retry_at is None


@pytest.mark.asyncio
async def test_transient_failure_reaches_terminal_dead_letter_after_max_attempts(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.add(
        SourceRegistry(
            code="mock-terminal", display_name="Mock", base_url="https://example.invalid"
        )
    )
    await session.commit()

    async def unavailable(*_args: object, **_kwargs: object) -> None:
        raise httpx.ConnectError("synthetic outage")

    monkeypatch.setattr("app.workers.jobs.ingest_raw_record", unavailable)
    payload = {"source_record_id": "notice-1", "raw_payload": {"title": "Synthetic"}}

    with pytest.raises(Retry):
        await ingest_record({"session": session}, "mock-terminal", payload)
    with pytest.raises(Retry):
        await ingest_record({"session": session}, "mock-terminal", payload)
    result = await ingest_record({"session": session}, "mock-terminal", payload)

    failure = await session.scalar(
        select(JobFailure).where(JobFailure.payload_json["source_code"].astext == "mock-terminal")
    )
    assert result["status"] == "dead_lettered"
    assert failure is not None
    assert failure.attempts == 3
    assert failure.dead_lettered is True
    assert failure.next_retry_at is None
