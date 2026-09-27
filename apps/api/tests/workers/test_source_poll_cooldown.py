"""Source cooldowns are durable PostgreSQL state shared by cron and queued workers."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from arq import Retry
from arq.connections import ArqRedis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from app.models import IngestRun, JobFailure, RawRecord, SourceRegistry
from app.sources.base import DiscoveryPage, RawSourceRecord
from app.sources.http import ResilientHttpClient
from app.workers import jobs


class HttpPollingAdapter:
    def __init__(self, client: ResilientHttpClient) -> None:
        self.client = client

    async def discover(self, _cursor: str | None) -> DiscoveryPage:
        await self.client.request("GET", "https://source.example/records")
        return DiscoveryPage(next_cursor="synthetic-finished")


class EmptyAdapter:
    async def discover(self, _cursor: str | None) -> DiscoveryPage:
        return DiscoveryPage(next_cursor="synthetic-finished")


@pytest.mark.asyncio
@pytest.mark.parametrize("max_attempts", [1, 3])
async def test_server_cooldown_gates_direct_cron_and_queued_polling_until_due(
    worker_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    max_attempts: int,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    initial = now
    calls = 0

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return now

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "60"}, request=request)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(jobs, "datetime", Clock)
    monkeypatch.setattr("app.sources.http.time.time", lambda: now.timestamp())
    ctx = {"session_factory": worker_session_factory}
    async with ResilientHttpClient(
        transport=httpx.MockTransport(handler), total_timeout_seconds=0.02,
        max_attempts=max_attempts, jitter=lambda _: 0,
    ) as client:
        monkeypatch.setattr(
            jobs, "source_adapters", lambda: {"cooldown": HttpPollingAdapter(client)}
        )
        with pytest.raises(Retry) as retry:
            await jobs.poll_source(ctx, "cooldown")
        assert retry.value.defer_score == 60_000

        async with worker_session_factory() as verify:
            failure = await verify.scalar(select(JobFailure))
            assert failure is not None
            assert failure.next_retry_at == initial + timedelta(seconds=60)
            assert failure.attempts == 1 and failure.dead_lettered is False

        assert (await jobs.poll_source(ctx, "cooldown"))["status"] == "deferred"
        assert await jobs.poll_configured_sources(ctx) == {"cooldown": "deferred"}
        now = initial + timedelta(seconds=59)
        assert (await jobs.poll_source(ctx, "cooldown"))["status"] == "deferred"
        assert calls == 1
        async with worker_session_factory() as verify:
            assert await verify.scalar(select(func.count()).select_from(IngestRun)) == 1

        now = initial + timedelta(seconds=60)
        assert (await jobs.poll_source(ctx, "cooldown"))["status"] == "success"
        assert calls == 2
        async with worker_session_factory() as verify:
            failure = await verify.scalar(select(JobFailure))
            assert failure is not None and failure.attempts == 0
            assert failure.next_retry_at is None and failure.dead_lettered is False
            assert await verify.scalar(select(func.count()).select_from(IngestRun)) == 2


@pytest.mark.asyncio
async def test_excessive_server_delay_stays_terminal_until_operator_replay(
    worker_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, headers={"Retry-After": "9" * 400}, request=request)

    async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(jobs, "source_adapters", lambda: {"review": HttpPollingAdapter(client)})
        ctx = {"session_factory": worker_session_factory}
        assert (await jobs.poll_source(ctx, "review"))["status"] == "dead_lettered"
        assert (await jobs.poll_source(ctx, "review"))["status"] == "dead_lettered"
        assert await jobs.poll_configured_sources(ctx) == {"review": "dead_lettered"}
    assert calls == 1
    async with worker_session_factory() as verify:
        failure = await verify.scalar(select(JobFailure))
        assert failure is not None and failure.attempts == 1
        assert failure.dead_lettered and failure.next_retry_at is None
        assert "review" in failure.error_message.lower()


@pytest.mark.asyncio
async def test_same_source_is_serialized_while_another_source_can_poll(
    worker_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return httpx.Response(429, headers={"Retry-After": "60"}, request=request)

    async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            jobs, "source_adapters",
            lambda: {"locked": HttpPollingAdapter(client), "independent": EmptyAdapter()},
        )
        ctx = {"session_factory": worker_session_factory}
        first = asyncio.create_task(jobs.poll_source(ctx, "locked"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            second = await asyncio.wait_for(jobs.poll_source(ctx, "locked"), timeout=5)
            assert second["status"] == "in_progress"
            independent = await asyncio.wait_for(jobs.poll_source(ctx, "independent"), timeout=5)
            assert independent["status"] == "success"
        finally:
            release.set()
            with pytest.raises(Retry):
                await first
        assert calls == 1
        assert (await jobs.poll_source(ctx, "locked"))["status"] == "deferred"


@pytest.mark.asyncio
async def test_cancellation_releases_the_source_lock(
    worker_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()

    class BlockingAdapter:
        async def discover(self, _cursor: str | None) -> DiscoveryPage:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    monkeypatch.setattr(jobs, "source_adapters", lambda: {"cancelled": BlockingAdapter()})
    ctx = {"session_factory": worker_session_factory}
    task = asyncio.create_task(jobs.poll_source(ctx, "cancelled"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    async with worker_session_factory() as verify:
        assert await verify.scalar(
            text("SELECT count(*) FROM pg_locks "
                 "WHERE locktype = 'advisory' AND classid = :namespace"),
            {"namespace": jobs.SOURCE_POLL_LOCK_NAMESPACE},
        ) == 0
    monkeypatch.setattr(jobs, "source_adapters", lambda: {"cancelled": EmptyAdapter()})
    assert (await jobs.poll_source(ctx, "cancelled"))["status"] == "success"


@pytest.mark.asyncio
async def test_supplied_connection_session_keeps_its_outer_transaction(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(session.bind, AsyncConnection)
    connection = session.bind
    outer = connection.get_transaction()
    assert outer is not None and outer.is_active
    session.add(SourceRegistry(
        code="supplied", display_name="Supplied", base_url="https://example.invalid"
    ))
    await session.flush()
    monkeypatch.setattr(jobs, "source_adapters", lambda: {"supplied": EmptyAdapter()})
    assert (await jobs.poll_source({"session": session}, "supplied"))["status"] == "success"
    assert connection.get_transaction() is outer and outer.is_active
    assert await session.scalar(select(SourceRegistry).where(SourceRegistry.code == "supplied"))


@pytest.mark.asyncio
async def test_poll_commits_raw_and_checkpoint_before_releasing_its_connection(
    worker_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordAdapter:
        async def discover(self, _cursor: str | None) -> DiscoveryPage:
            return DiscoveryPage(records=(RawSourceRecord(
                source_record_id="durable-1",
                raw_payload={
                    "title": "Synthetic tender", "buyer_name": "Synthetic buyer",
                    "lifecycle_stage": "tender", "is_synthetic": True,
                },
            ),), next_cursor="durable-checkpoint")

    monkeypatch.setattr(jobs, "source_adapters", lambda: {"durable-poll": RecordAdapter()})
    result = await jobs.poll_source({"session_factory": worker_session_factory}, "durable-poll")
    assert result["status"] == "success"
    async with worker_session_factory() as verify:
        raw = await verify.scalar(select(RawRecord))
        run = await verify.scalar(select(IngestRun))
        assert raw is not None and raw.normalization_status == "normalized"
        assert run is not None and run.status == "success" and run.fetched_count == 1
        assert run.cursor_after == "durable-checkpoint"


@pytest.mark.asyncio
async def test_borrowed_connection_can_poll_twice_without_unlock_leaving_a_transaction(
    worker_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class RecordAdapter:
        async def discover(self, _cursor: str | None) -> DiscoveryPage:
            nonlocal calls
            calls += 1
            return DiscoveryPage(records=(RawSourceRecord(
                source_record_id=f"borrowed-{calls}",
                raw_payload={
                    "title": f"Synthetic tender {calls}", "buyer_name": "Synthetic buyer",
                    "lifecycle_stage": "tender", "is_synthetic": True,
                },
            ),), next_cursor=f"borrowed-checkpoint-{calls}")

    adapter = RecordAdapter()
    monkeypatch.setattr(jobs, "source_adapters", lambda: {"borrowed-poll": adapter})
    async with worker_session_factory() as template:
        assert isinstance(template.bind, AsyncEngine)
        async with (
            template.bind.connect() as connection,
            async_sessionmaker(connection, expire_on_commit=False)() as borrowed,
        ):
            ctx = {"session": borrowed}
            for _ in range(2):
                assert (await jobs.poll_source(ctx, "borrowed-poll"))["status"] == "success"
                assert not connection.in_transaction()
    async with worker_session_factory() as verify:
        assert await verify.scalar(select(func.count()).select_from(RawRecord)) == 2
        runs = (await verify.scalars(select(IngestRun))).all()
        assert len(runs) == 2 and all(run.status == "success" for run in runs)
        assert {run.cursor_after for run in runs} == {
            "borrowed-checkpoint-1", "borrowed-checkpoint-2",
        }


@pytest.mark.asyncio
async def test_sql_failure_releases_the_source_lock_after_rollback(
    worker_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_query(session: AsyncSession, **_kwargs: object) -> list[object]:
        await session.execute(text("SELECT 1 / 0"))
        return []

    monkeypatch.setattr(jobs, "source_adapters", lambda: {"sql-failure": EmptyAdapter()})
    monkeypatch.setattr(jobs, "_pending_normalization_ids", broken_query)
    ctx = {"session_factory": worker_session_factory}
    assert (await jobs.poll_source(ctx, "sql-failure"))["status"] == "dead_lettered"
    assert (await jobs.poll_source(ctx, "sql-failure"))["status"] == "dead_lettered"
    async with worker_session_factory() as verify:
        assert await verify.scalar(
            text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
        ) == 0


@pytest.mark.asyncio
async def test_reconciler_does_not_move_a_due_poll_behind_its_own_entry_gate(
    worker_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_code = "reconciled-cooldown"
    due_at = datetime.now(UTC) - timedelta(seconds=1)
    stable_key = jobs.job_key("poll_source", source_code, {"source_code": source_code})
    async with worker_session_factory() as setup:
        setup.add(JobFailure(
            job_type="poll_source", job_key=stable_key, attempts=1,
            error_class="RetryAfterDeadlineExceeded", error_message="safe",
            payload_json={"source_code": source_code}, dead_lettered=False,
            next_retry_at=due_at,
        ))
        await setup.commit()
    redis = ArqRedis()
    enqueue = AsyncMock(return_value=object())
    monkeypatch.setattr(redis, "enqueue_job", enqueue)
    monkeypatch.setattr(jobs, "source_adapters", lambda: {source_code: EmptyAdapter()})
    ctx = {"session_factory": worker_session_factory, "redis": redis}
    try:
        assert await jobs.reconcile_failed_jobs(ctx) == {"requeued": 1}
        enqueue.assert_awaited_once_with(
            "poll_source", source_code, _job_id=stable_key, _queue_name=jobs.WORKER_QUEUE
        )
        async with worker_session_factory() as verify:
            failure = await verify.scalar(select(JobFailure))
            assert failure is not None and failure.next_retry_at == due_at
        assert (await jobs.poll_source(ctx, source_code))["status"] == "success"
    finally:
        await redis.aclose()
