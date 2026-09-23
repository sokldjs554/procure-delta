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
