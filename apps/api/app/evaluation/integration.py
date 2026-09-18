"""Opt-in measurements against real local services; never fall back to an emulation."""
from __future__ import annotations

import asyncio
import os
import time
from collections import Counter
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .metrics import percentile
from .performance import LOCAL_HOSTS, require_benchmark_database, synthetic_record
from .provenance import environment


def require_local_http(url: str) -> None:
    value = urlsplit(url)
    if (value.scheme not in {'http', 'https'} or value.hostname not in LOCAL_HOSTS | {'api'}
            or value.username or value.password or value.query or value.fragment
            or value.path not in {'', '/'}):
        raise ValueError('service load is restricted to a local HTTP origin without credentials')


def require_benchmark_redis(url: str) -> None:
    value = urlsplit(url)
    if (value.scheme != 'redis' or value.hostname not in LOCAL_HOSTS | {'redis'}
            or value.path != '/15'):
        raise ValueError('queue load requires a local, dedicated Redis database 15')


async def service_load(base_url: str, requests: int, concurrency: int) -> dict[str, Any]:
    require_local_http(base_url)
    if not 1 <= requests <= 10000 or not 1 <= concurrency <= 100:
        raise ValueError('requests 1..10000 and concurrency 1..100 required')
    outcomes: dict[str, Any] = {}
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        login = await client.post('/api/v1/auth/demo-login', json={})
        login.raise_for_status()
        inbox = await client.get('/api/v1/opportunities', params={'limit': 1})
        inbox.raise_for_status()
        rows = inbox.json()['items']
        if not rows:
            raise ValueError('seed actual data before measuring; an empty feed is not a benchmark')
        targets = {
            'inbox': '/api/v1/opportunities?limit=20',
            'search': '/api/v1/opportunities?q=cloud&limit=20',
            'detail': '/api/v1/opportunities/' + str(rows[0]['id']),
        }
        secret = os.getenv('DEMO_OPERATOR_SECRET')
        if secret:
            response = await client.post('/api/v1/auth/demo-login',
                json={'operator_secret': secret})
            response.raise_for_status()
            targets['admin'] = '/api/v1/admin/pipeline'
        else:
            outcomes['admin'] = {'status': 'not_run', 'reason': 'operator secret not supplied'}
        for name, endpoint in targets.items():
            warmup = await client.get(endpoint)
            warmup.raise_for_status()
            semaphore = asyncio.Semaphore(concurrency)

            async def sample(
                bound_semaphore: asyncio.Semaphore = semaphore,
                bound_endpoint: str = endpoint,
            ) -> tuple[float, str]:
                async with bound_semaphore:
                    started = time.perf_counter()
                    try:
                        result = await client.get(bound_endpoint)
                        status = str(result.status_code)
                    except httpx.HTTPError:
                        status = 'transport_error'
                    return (time.perf_counter() - started) * 1000, status

            started = time.perf_counter()
            samples = await asyncio.gather(*(sample() for _ in range(requests)))
            elapsed = time.perf_counter() - started
            statuses = dict(Counter(status for _, status in samples))
            timings = [latency for latency, _ in samples]
            outcomes[name] = {
                'status': 'measured', 'requests': requests, 'concurrency': concurrency,
                'status_counts': statuses, 'error_count': sum(n for s,
                    n in statuses.items() if s != '200'),
                'p50_ms': percentile(timings, 50), 'p95_ms': percentile(timings, 95),
                'elapsed_seconds': elapsed, 'requests_per_second': requests / elapsed,
                'warmup_requests_excluded': 1,
            }
    return {'scope': 'real_local_http', 'environment': environment(), 'endpoints': outcomes,
            'client_observed_only': True, 'arq_throughput': None,
            'successful': all(v.get('error_count', 0) == 0 for v in outcomes.values())}


async def queue_load(records: int) -> dict[str, Any]:
    if not 1 <= records <= 50000:
        raise ValueError('queue benchmark accepts 1..50000 records')
    database_url = os.environ['BENCH_DATABASE_URL']
    redis_url = os.environ['BENCH_REDIS_URL']
    require_benchmark_database(database_url)
    require_benchmark_redis(redis_url)
    # Imports intentionally deferred: missing services/dependencies must not report success.
    from arq.connections import RedisSettings, create_pool
    from arq.worker import Worker
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models import RawRecord, SourceRegistry
    from app.workers.jobs import ingest_record

    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = uuid4().hex
    code, queue = 'benchmark-' + run_id, 'arq:procure-delta:bench:' + run_id
    redis = await create_pool(RedisSettings.from_dsn(redis_url), default_queue_name=queue)
    jobs = []
    worker = None
    try:
        async with factory() as session:
            source = SourceRegistry(code=code, display_name='Synthetic load run',
                                    base_url='https://example.invalid', enabled=False)
            session.add(source)
            await session.commit()
            source_id = source.id
        started = time.perf_counter()
        for i in range(records):
            job = await redis.enqueue_job('ingest_record', code,
                synthetic_record(i).model_dump(mode='json'),
                                          _job_id=f'{run_id}-{i}')
            if job is None:
                raise RuntimeError('unique benchmark enqueue was unexpectedly deduplicated')
            jobs.append(job)
        enqueue_seconds = time.perf_counter() - started
        started = time.perf_counter()
        worker = Worker([ingest_record], redis_pool=redis, queue_name=queue, burst=True,
                        handle_signals=False, max_jobs=10, job_timeout=60,
                        ctx={'session_factory': factory})
        await asyncio.wait_for(worker.async_run(), timeout=max(180, records * 2))
        elapsed = time.perf_counter() - started
        statuses: Counter[str] = Counter()
        for job in jobs:
            result = await job.result(timeout=2)
            statuses[result['status']] += 1
        async with factory() as session:
            normalized = await session.scalar(select(func.count()).select_from(RawRecord).where(
                RawRecord.source_id == source_id, RawRecord.normalization_status == 'normalized'))
        complete = statuses.get('created', 0) == records and normalized == records
        return {'scope': 'real_redis_arq_postgresql', 'synthetic': True,
                'environment': environment(), 'records': records, 'status_counts': dict(statuses),
                'normalized_records': normalized, 'successful': complete,
                'enqueue_seconds': enqueue_seconds, 'worker_seconds': elapsed,
                'arq_records_per_second': records / elapsed if complete else None,
                'max_jobs': 10, 'source_code': code,
                'limitation': 'Local ingestion only; OCR/external LLM and attachments excluded.'}
    finally:
        # Only this random run's queue/results; never FLUSHDB or delete other jobs.
        if worker is not None:
            await worker.close()
        else:
            await redis.aclose()
        await engine.dispose()


async def prepare_scale_source(source_code: str) -> dict[str, Any]:
    """Explicit benchmark setup after throughput timing: these records have no documents."""
    database_url = os.environ['BENCH_DATABASE_URL']
    require_benchmark_database(database_url)
    if not source_code.startswith('benchmark-'):
        raise ValueError('only this synthetic benchmark namespace may be prepared')
    from pathlib import Path

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.documents.service import persist_and_parse_attachments
    from app.models import OpportunityVersion, RawRecord, SourceRegistry

    started = time.perf_counter()
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            source = await session.scalar(select(SourceRegistry).where(
                SourceRegistry.code == source_code, SourceRegistry.enabled.is_(False)))
            if source is None:
                raise ValueError('synthetic benchmark source is missing')
            rows = (await session.execute(select(OpportunityVersion, RawRecord).join(
                RawRecord, OpportunityVersion.raw_record_id == RawRecord.id
            ).where(RawRecord.source_id == source.id))).all()
            for index, (version, raw) in enumerate(rows):
                if (
                    raw.payload_json.get('is_synthetic') is not True
                    or raw.payload_json.get('attachments')
                ):
                    raise ValueError(
                        'scale seed only completes known empty synthetic document manifests'
                    )
                await persist_and_parse_attachments(
                    session, opportunity_version_id=version.id, refs=[],
                    allowed_source_host='example.invalid',
                        storage_root=Path('/tmp/procure-delta-bench'))
                if (index + 1) % 500 == 0:
                    await session.commit()
            await session.commit()
            return {'synthetic_empty_manifests': len(rows),
                    'elapsed_seconds': time.perf_counter() - started,
                    'included_in_queue_throughput': False}
    finally:
        await engine.dispose()
