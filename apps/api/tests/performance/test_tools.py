import asyncio
import importlib

import pytest


def tools():
    assert importlib.util.find_spec('app.evaluation.performance'), 'performance harness missing'
    return importlib.import_module('app.evaluation.performance')


def test_dedicated_database_guard_rejects_application_and_remote_targets():
    m = tools()
    for url in ['postgresql://u:p@localhost/procure_delta',
                'postgresql://u:p@remote.example/bench_test',
                'postgresql://u:p@localhost/postgres']:
        with pytest.raises(ValueError):
            m.require_benchmark_database(url)
    m.require_benchmark_database('postgresql+psycopg://u:p@localhost/procure_delta_bench')


def test_cpu_measurement_cannot_masquerade_as_api_or_database_load():
    report = tools().cpu_benchmark(25)
    assert report['scope'] == 'cpu_only_production_functions'
    assert report['normalized_records'] == 25
    assert report['database_calls'] == report['external_api_calls'] == 0
    assert report['api_p95_ms'] is None and report['arq_records_per_second'] is None


def test_synthetic_scale_values_are_deterministic_and_varied():
    m = tools()
    assert m.synthetic_record(8) == m.synthetic_record(8)
    assert m.synthetic_record(8).raw_payload != m.synthetic_record(9).raw_payload


def test_http_failure_drill_runs_actual_retry_code_with_injected_transport():
    assert importlib.util.find_spec('app.evaluation.failure'), 'failure drills missing'
    module = importlib.import_module('app.evaluation.failure')
    report = asyncio.run(module.http_drills())
    assert report['scope'] == 'http_transport_injection'
    assert all(row['passed'] for row in report['cases'])
    assert report['database_outage_verified'] is False
    assert report['redis_restart_verified'] is False
