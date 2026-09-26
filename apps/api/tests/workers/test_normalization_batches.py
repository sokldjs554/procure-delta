from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import JobFailure, RawRecord, SourceRegistry
from app.sources.base import DiscoveryPage
from app.workers import jobs

EntryPoint = Literal["poll", "reconcile"]
SOURCE_CODE = "normalization-batch"


class EmptyAdapter:
    async def discover(self, _cursor: str | None) -> DiscoveryPage:
        return DiscoveryPage()


def configure_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        jobs, "get_settings", lambda: Settings(_env_file=None, normalization_batch_size=2)
    )
    monkeypatch.setattr(jobs, "source_adapters", lambda: {SOURCE_CODE: EmptyAdapter()})


async def seed_pending(
    factory: async_sessionmaker[AsyncSession], count: int
) -> None:
    async with factory() as setup:
        source = SourceRegistry(
            code=SOURCE_CODE, display_name="Synthetic batch", base_url="https://example.invalid"
        )
        setup.add(source)
        await setup.flush()
        # Reverse insertion order and tied timestamps require a stable UUID tie-breaker.
        for index in reversed(range(1, count + 1)):
            setup.add(
                RawRecord(
                    id=UUID(int=index),
                    source_id=source.id,
                    source_record_id=f"pending-{index}",
                    payload_json={
                        "title": f"Synthetic pending {index}",
                        "buyer_name": "Synthetic buyer",
                        "lifecycle_stage": "tender",
                        "is_synthetic": True,
                    },
                    payload_sha256=f"{index:064x}",
                    fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
        await setup.commit()


async def run_batch(factory: async_sessionmaker[AsyncSession], entrypoint: EntryPoint) -> None:
    # Each invocation gets fresh worker context and database sessions, like a restart.
    ctx = {"session_factory": factory}
    if entrypoint == "poll":
        result = await jobs.poll_source(ctx, SOURCE_CODE)
        assert result["status"] == "success"
    else:
        result = await jobs.reconcile_pending_normalizations(ctx)
        assert result["failed"] == 0
        assert result["normalized"] <= 2


async def normalized_ids(factory: async_sessionmaker[AsyncSession]) -> list[int]:
    async with factory() as verify:
        ids = await verify.scalars(
            select(RawRecord.id)
            .where(RawRecord.normalization_status == "normalized")
            .order_by(RawRecord.id)
        )
        return [identifier.int for identifier in ids]


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["poll", "reconcile"])
async def test_normalization_drains_bounded_batches_after_worker_restart(
    worker_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: EntryPoint,
) -> None:
    configure_batch(monkeypatch)
    await seed_pending(worker_session_factory, 7)

    for expected in ([1, 2], [1, 2, 3, 4], [1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6, 7]):
        await run_batch(worker_session_factory, entrypoint)
        assert await normalized_ids(worker_session_factory) == expected

    await run_batch(worker_session_factory, entrypoint)
    assert await normalized_ids(worker_session_factory) == [1, 2, 3, 4, 5, 6, 7]


@pytest.mark.asyncio
async def test_normalization_prioritizes_oldest_backlog_before_lower_uuid(
    worker_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_batch(monkeypatch)
    await seed_pending(worker_session_factory, 3)
    async with worker_session_factory() as setup:
        newest = await setup.get_one(RawRecord, UUID(int=1))
        newest.fetched_at = datetime(2026, 2, 1, tzinfo=UTC)
        await setup.commit()

    await run_batch(worker_session_factory, "reconcile")

    assert await normalized_ids(worker_session_factory) == [2, 3]


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["poll", "reconcile"])
async def test_normalization_filters_retry_holds_before_batch_limit(
    worker_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: EntryPoint,
) -> None:
    configure_batch(monkeypatch)
    await seed_pending(worker_session_factory, 6)
    now = datetime.now(UTC)
    async with worker_session_factory() as setup:
        for index, attempts, terminal, retry_at in (
            (1, 1, False, now + timedelta(hours=1)),
            (2, 1, True, None),
            (3, 3, False, now - timedelta(seconds=1)),
            (4, 1, False, None),
        ):
            setup.add(
                JobFailure(
                    job_type="normalize_record",
                    job_key=jobs.job_key(
                        "normalize_record", "raw", {"raw_record_id": str(UUID(int=index))}
                    ),
                    attempts=attempts,
                    error_class="OperationalError",
                    error_message="OperationalError",
                    payload_json={"raw_record_id": str(UUID(int=index))},
                    dead_lettered=terminal,
                    next_retry_at=retry_at,
                )
            )
        await setup.commit()

    await run_batch(worker_session_factory, entrypoint)
    assert await normalized_ids(worker_session_factory) == [5, 6]
    await run_batch(worker_session_factory, entrypoint)
    assert await normalized_ids(worker_session_factory) == [5, 6]

    # A deferred row becomes eligible from durable retry state, without an in-memory cursor.
    async with worker_session_factory() as setup:
        deferred = await setup.scalar(
            select(JobFailure).where(
                JobFailure.payload_json["raw_record_id"].astext == str(UUID(int=1))
            )
        )
        assert deferred is not None
        deferred.next_retry_at = now - timedelta(seconds=1)
        await setup.commit()
    await run_batch(worker_session_factory, entrypoint)
    assert await normalized_ids(worker_session_factory) == [1, 5, 6]


@pytest.mark.asyncio
async def test_poll_batch_preserves_other_sources_pending_work(
    worker_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_batch(monkeypatch)
    await seed_pending(worker_session_factory, 3)
    async with worker_session_factory() as setup:
        source = SourceRegistry(
            code="unrelated-batch", display_name="Unrelated", base_url="https://example.invalid"
        )
        setup.add(source)
        await setup.flush()
        setup.add(
            RawRecord(
                id=UUID(int=10),
                source_id=source.id,
                source_record_id="unrelated-pending",
                payload_json={"title": "Invalid unrelated raw should remain pending"},
                payload_sha256="a" * 64,
                fetched_at=datetime(2025, 1, 1, tzinfo=UTC),
            )
        )
        await setup.commit()

    await run_batch(worker_session_factory, "poll")
    assert await normalized_ids(worker_session_factory) == [1, 2]
    async with worker_session_factory() as verify:
        unrelated = await verify.get_one(RawRecord, UUID(int=10))
        assert unrelated.normalization_status == "pending"


@pytest.mark.parametrize("size", [0, -1, 1001])
def test_normalization_batch_size_rejects_unbounded_settings(size: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, normalization_batch_size=size)
