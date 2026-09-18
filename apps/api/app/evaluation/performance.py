from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.engine import make_url

from app.delta.engine import compute_delta
from app.models import RawRecord
from app.services.normalize import normalize_raw_record
from app.sources.base import RawSourceRecord

from .metrics import percentile
from .provenance import environment
from .replay import decision_for
from .runner import snapshot

LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1', 'postgres'}


def require_benchmark_database(url: str) -> None:
    parsed = make_url(url)
    name = parsed.database or ''
    if parsed.host not in LOCAL_HOSTS or not name.endswith(('_test', '_bench')):
        raise ValueError('destructive benchmarks require a local dedicated *_test or *_bench DB')
    if parsed.get_backend_name() != 'postgresql':
        raise ValueError('the integration benchmark requires PostgreSQL, not an emulation')


def synthetic_record(index: int) -> RawSourceRecord:
    if index < 0:
        raise ValueError('index cannot be negative')
    date = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=index % 14400)
    return RawSourceRecord(source_record_id=f'synthetic-load-{index:07d}', raw_payload={
        'title': f'Synthetic cloud OCR service {index:07d}',
        'buyer_name': f'Synthetic Agency {index % 71}', 'procurement_type': 'services',
        'lifecycle_stage': 'tender', 'status': 'open',
        'estimated_amount': str(50000000 + (index * 7919) % 300000000), 'currency': 'KRW',
        'published_at': date.isoformat(), 'closes_at': '2026-10-30T09:00:00+00:00',
        'regions': ['Seoul' if index % 3 else 'Busan'],
        'required_certifications': ['ISO 27001'], 'required_capabilities': ['cloud', 'OCR'],
        'is_synthetic': True,
    }, source_url=f'https://example.invalid/load/{index}')


def cpu_benchmark(records: int = 50000) -> dict[str, Any]:
    if not 1 <= records <= 1000000:
        raise ValueError('records must be between 1 and 1,000,000')
    profile = {'regions': ['Seoul'], 'certifications': ['ISO 27001'],
               'industries': ['services'], 'capabilities': ['cloud', 'OCR'],
               'min_contract_amount': '10000000', 'max_contract_amount': '500000000',
               'contract_currency': 'KRW'}
    as_of = datetime(2026, 9, 16, tzinfo=UTC)
    timings: dict[str, list[float]] = {'normalize': [], 'eligibility_and_rank': [], 'delta': []}
    digest = hashlib.sha256()
    started = time.perf_counter()
    for i in range(records):
        record = synthetic_record(i)
        digest.update(record.model_dump_json().encode())
        raw = RawRecord(id=UUID(int=i + 100), source_id=UUID(int=1),
                        source_record_id=record.source_record_id, payload_json=record.raw_payload,
                        payload_sha256=(
                            hashlib.sha256(record.model_dump_json().encode()).hexdigest()
                        ),
                        fetched_at=as_of)
        step = time.perf_counter()
        normalize_raw_record(raw, source_code='synthetic-load')
        timings['normalize'].append((time.perf_counter() - step) * 1000)
        step = time.perf_counter()
        decision_for(record.raw_payload, profile, as_of=as_of, evidence_id=record.source_record_id)
        timings['eligibility_and_rank'].append((time.perf_counter() - step) * 1000)
        if i % 10 == 0:
            step = time.perf_counter()
            before = record.raw_payload
            after = {**before,
                'regions': ['Busan'] if before['regions'] == ['Seoul'] else ['Seoul']}
            compute_delta(snapshot(1, before), snapshot(2, after))
            timings['delta'].append((time.perf_counter() - step) * 1000)
    elapsed = time.perf_counter() - started
    return {
        'scope': 'cpu_only_production_functions', 'synthetic': True,
        'environment': environment(), 'generated_dataset_sha256': digest.hexdigest(),
        'normalized_records': records, 'ranked_records': records,
        'delta_pairs': len(timings['delta']), 'database_calls': 0, 'external_api_calls': 0,
        'api_p95_ms': None, 'arq_records_per_second': None, 'elapsed_seconds': elapsed,
        'cpu_pipeline_records_per_second': records / elapsed,
        'stages_ms': {k: {'samples': len(v), 'p50': percentile(v, 50), 'p95': percentile(v, 95)}
                      for k, v in timings.items()},
        'limitation': 'CPU loop only; not PostgreSQL ingest, Redis throughput or SaaS capacity.',
    }
