import pytest


def test_http_benchmark_cannot_send_credentials_to_remote_host():
    from app.evaluation.integration import require_local_http
    require_local_http('http://localhost:18000')
    for url in ['https://example.com', 'http://localhost@evil.test', 'file:///etc/passwd',
        'http://localhost/a?token=x']:
        with pytest.raises(ValueError):
            require_local_http(url)


def test_queue_benchmark_requires_isolated_redis_database():
    from app.evaluation.integration import require_benchmark_redis
    require_benchmark_redis('redis://redis:6379/15')
    for url in ['redis://redis:6379/0', 'redis://example.com:6379/15']:
        with pytest.raises(ValueError):
            require_benchmark_redis(url)


def test_backfill_benchmark_requires_a_real_resume_boundary(monkeypatch):
    import asyncio

    from app.evaluation.integration import backfill_load

    monkeypatch.setenv(
        "BENCH_DATABASE_URL",
        "postgresql+psycopg://procure_delta:procure_delta@postgres:5432/procure_delta_bench",
    )
    with pytest.raises(ValueError, match="100..10000"):
        asyncio.run(backfill_load(99))
    with pytest.raises(ValueError, match="page_size"):
        asyncio.run(backfill_load(1000, page_size=0))
    with pytest.raises(ValueError, match="stop before the final page"):
        asyncio.run(backfill_load(1000, page_size=100, first_batch_pages=10))


@pytest.mark.asyncio
async def test_backfill_benchmark_resumes_at_both_page_budget_limits(monkeypatch):
    from app.evaluation.integration import backfill_load
    from tests.conftest import TEST_DATABASE_URL

    monkeypatch.setenv("BENCH_DATABASE_URL", TEST_DATABASE_URL)
    result = await backfill_load(200, page_size=1, first_batch_pages=100)

    assert result["successful"] is True
    assert result["first_batch_pages"] == 100
    assert result["resume_cursor"] == "100"
    assert result["resumed_pages"] == 100
    assert result["ingest_runs"] == result["successful_runs"] == 200
    assert result["normalized_records"] == 200
    assert result["resumed_from_checkpoint"] is True


@pytest.mark.asyncio
async def test_backfill_drains_pages_larger_than_normalization_cap_without_touching_other_sources(
    monkeypatch, worker_session_factory,
):
    from datetime import UTC, datetime

    from app.config import Settings
    from app.evaluation.integration import backfill_load
    from app.models import RawRecord, SourceRegistry
    from app.workers import jobs
    from tests.conftest import TEST_DATABASE_URL

    monkeypatch.setenv("BENCH_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(
        jobs, "get_settings", lambda: Settings(_env_file=None, normalization_batch_size=15)
    )
    monkeypatch.setattr(
        "app.evaluation.integration.get_settings",
        lambda: Settings(_env_file=None, normalization_batch_size=15),
    )
    async with worker_session_factory() as setup:
        source = SourceRegistry(
            code="unrelated-backfill", display_name="Unrelated", base_url="https://example.invalid"
        )
        setup.add(source)
        await setup.flush()
        unrelated = RawRecord(
            source_id=source.id,
            source_record_id="unrelated-pending",
            payload_json={"title": "Must remain untouched"},
            payload_sha256="a" * 64,
            fetched_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        setup.add(unrelated)
        await setup.commit()
        unrelated_id = unrelated.id

    real_reconcile = jobs.reconcile_pending_normalizations
    batch_counts = []

    async def observe_reconciliation(ctx, **kwargs):
        outcome = await real_reconcile(ctx, **kwargs)
        batch_counts.append(outcome["normalized"])
        return outcome

    monkeypatch.setattr(jobs, "reconcile_pending_normalizations", observe_reconciliation)
    result = await backfill_load(100, page_size=50, first_batch_pages=1)

    assert result["successful"] is True
    assert result["normalized_records"] == 100
    assert result["normalization_batch_size"] == 15
    assert result["normalized_during_discovery"] == 30
    assert result["normalization_reconciliation_batches"] == 5
    assert result["normalized_during_reconciliation"] == 70
    assert result["normalization_reconciliation_stop"] == "complete"
    assert result["elapsed_seconds"] >= result["normalization_reconciliation_seconds"] > 0
    assert batch_counts == [15, 15, 15, 15, 10]
    async with worker_session_factory() as verify:
        untouched = await verify.get_one(RawRecord, unrelated_id)
        assert untouched.normalization_status == "pending"


@pytest.mark.asyncio
async def test_backfill_stops_when_reconciliation_makes_no_database_progress(monkeypatch):
    from app.config import Settings
    from app.evaluation.integration import backfill_load
    from app.workers import jobs
    from tests.conftest import TEST_DATABASE_URL

    monkeypatch.setenv("BENCH_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(
        jobs, "get_settings", lambda: Settings(_env_file=None, normalization_batch_size=15)
    )
    monkeypatch.setattr(
        "app.evaluation.integration.get_settings",
        lambda: Settings(_env_file=None, normalization_batch_size=15),
    )

    async def stalled_reconciliation(ctx, **kwargs):
        # A misleading worker summary must not replace the measured PostgreSQL count.
        return {"normalized": 15, "failed": 0}

    monkeypatch.setattr(jobs, "reconcile_pending_normalizations", stalled_reconciliation)
    result = await backfill_load(100, page_size=50, first_batch_pages=1)

    assert result["successful"] is False
    assert result["records_per_second"] is None
    assert result["normalized_records"] == 30
    assert result["normalization_reconciliation_batches"] == 1
    assert result["normalized_during_reconciliation"] == 0
    assert result["normalization_reconciliation_stop"] == "no_progress"
