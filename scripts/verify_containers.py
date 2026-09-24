"""Run an isolated local integration gate. Requires Docker Desktop, Node 22 and Python.

Never reads the user's .env, replaces origin, or touches the original project's DB volumes.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from statistics import median
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'artifacts/container'
PUBLIC_PERFORMANCE = ROOT / 'artifacts/performance'
FORBIDDEN_PUBLIC_KEYS = ('secret', 'password', 'cookie', 'authorization', 'token')


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_PUBLIC_KEYS):
                return True
            if _contains_forbidden_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _write_public_summary(destination: Path, payload: dict[str, object]) -> None:
    if _contains_forbidden_key(payload):
        raise RuntimeError(f'public summary contains a forbidden key: {destination.name}')
    PUBLIC_PERFORMANCE.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding='utf-8')


# Public destinations: artifacts/performance/queue.json, artifacts/performance/http.json,
# artifacts/performance/query-plans.json, artifacts/performance/backfill.json
def publish_public_measurements() -> None:
    queue_raw = json.loads((OUTPUT / 'queue-load.json').read_text(encoding='utf-8'))
    http_raw = json.loads((OUTPUT / 'http-load.json').read_text(encoding='utf-8'))
    query_raw = json.loads((OUTPUT / 'query-plans.json').read_text(encoding='utf-8'))
    backfill_raw = json.loads((OUTPUT / 'backfill.json').read_text(encoding='utf-8'))

    queue_summary: dict[str, object] = {
        'scope': queue_raw['scope'],
        'synthetic': queue_raw['synthetic'],
        'records': queue_raw['records'],
        'completed_records': queue_raw['normalized_records'],
        'elapsed_seconds': queue_raw['worker_seconds'],
        'records_per_second': queue_raw['arq_records_per_second'],
        'successful': queue_raw['successful'],
        'limitation': queue_raw['limitation'],
    }

    endpoints: dict[str, object] = {}
    total_requests = 0
    successful_requests = 0
    failed_requests = 0
    for name, raw in http_raw.get('endpoints', {}).items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            continue
        requests = raw.get('requests')
        errors = raw.get('error_count')
        if not isinstance(requests, int) or not isinstance(errors, int):
            continue
        total_requests += requests
        failed_requests += errors
        successful_requests += requests - errors
        endpoints[name] = {
            'status': raw.get('status'),
            'requests': requests,
            'concurrency': raw.get('concurrency'),
            'error_count': errors,
            'p50_ms': raw.get('p50_ms'),
            'p95_ms': raw.get('p95_ms'),
            'requests_per_second': raw.get('requests_per_second'),
        }
    http_summary: dict[str, object] = {
        'scope': http_raw['scope'],
        'synthetic': True,
        'requests': total_requests,
        'successful_requests': successful_requests,
        'failed_requests': failed_requests,
        'endpoints': endpoints,
        'client_observed_only': http_raw.get('client_observed_only') is True,
        'successful': http_raw.get('successful') is True,
    }

    def execution_times(rows: object) -> list[float]:
        values: list[float] = []
        if not isinstance(rows, list):
            return values
        for entry in rows:
            if not isinstance(entry, list) or not entry or not isinstance(entry[0], dict):
                continue
            value = entry[0].get('Execution Time')
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    before = execution_times(query_raw.get('before'))
    after = execution_times(query_raw.get('after'))
    if not before or not after:
        raise RuntimeError('query-plan summary lacks measured execution times')
    before_ms, after_ms = median(before), median(after)
    query_summary: dict[str, object] = {
        'scope': query_raw['scope'],
        'synthetic': True,
        'records': query_raw['rows'],
        'before': before_ms,
        'after': after_ms,
        'improvement_ratio': before_ms / after_ms if after_ms else None,
        'candidate_adopted': query_raw.get('candidate_adopted') is True,
        'candidate_rolled_back': query_raw.get('candidate_rolled_back') is True,
        'caution': query_raw.get('caution'),
    }

    backfill_summary: dict[str, object] = {
        'scope': backfill_raw['scope'],
        'synthetic': backfill_raw['synthetic'],
        'records': backfill_raw['records'],
        'page_size': backfill_raw['page_size'],
        'expected_pages': backfill_raw['expected_pages'],
        'first_batch_pages': backfill_raw['first_batch_pages'],
        'resumed_pages': backfill_raw['resumed_pages'],
        'ingest_runs': backfill_raw['ingest_runs'],
        'normalized_records': backfill_raw['normalized_records'],
        'resumed_from_checkpoint': backfill_raw['resumed_from_checkpoint'],
        'elapsed_seconds': backfill_raw['elapsed_seconds'],
        'records_per_second': backfill_raw['records_per_second'],
        'successful': backfill_raw['successful'],
        'limitation': backfill_raw['limitation'],
    }

    _write_public_summary(PUBLIC_PERFORMANCE / 'queue.json', queue_summary)
    _write_public_summary(PUBLIC_PERFORMANCE / 'http.json', http_summary)
    _write_public_summary(PUBLIC_PERFORMANCE / 'query-plans.json', query_summary)
    _write_public_summary(PUBLIC_PERFORMANCE / 'backfill.json', backfill_summary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--keep-running', action='store_true')
    parser.add_argument('--scale-records', type=int, default=1000)
    parser.add_argument('--backfill-records', type=int, default=2000)
    args = parser.parse_args()
    if not 1000 <= args.scale_records <= 50000:
        parser.error('--scale-records must be between 1000 and 50000')
    if not 1000 <= args.backfill_records <= 10000:
        parser.error('--backfill-records must be between 1000 and 10000')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {'started_at': datetime.now(UTC).isoformat(), 'passed': False,
                                'scope': 'isolated_container_integration', 'gates': []}
    gates: list[dict[str, object]] = []
    report['gates'] = gates

    def save() -> None:
        (OUTPUT / 'release-gate.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    missing = [name for name in ['docker', 'node', 'npm'] if shutil.which(name) is None]
    if missing:
        report.update(status='blocked', missing_tools=missing)
        save()
        print('Integration not run. Missing tools: ' + ', '.join(missing))
        raise SystemExit(2)
    project = 'procure-delta-verify-' + secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    environment = {**os.environ, 'COMPOSE_PROJECT_NAME': project, 'VERIFY_OPERATOR_SECRET': secret}
    report['compose_project'] = project
    compose = ['docker', 'compose', '--env-file', os.devnull,
               '-p', project, '-f', 'compose.verify.yml']

    def record_backend_subgates() -> None:
        checks = OUTPUT / 'checks.json'
        if not checks.is_file():
            return
        try:
            rows = json.loads(checks.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(rows, list):
            report['backend_subgates'] = rows
            save()

    def execute(name: str, command: list[str], cwd: Path = ROOT, timeout: int = 1200) -> None:
        executable = shutil.which(command[0]) or command[0]
        if os.name == 'nt' and executable.lower().endswith(('.cmd', '.bat')):
            command = ['cmd', '/d', '/c', executable, *command[1:]]
        print(f'Running: {name}', flush=True)
        start = time.perf_counter()
        try:
            result = subprocess.run(command, cwd=cwd, env=environment, text=True,
                                    encoding='utf-8', errors='replace', stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=timeout, check=False)
            text, code = result.stdout, result.returncode
        except subprocess.TimeoutExpired:
            text, code = 'Command exceeded its bounded timeout. No pass was recorded.', 124
        except OSError as error:
            text, code = type(error).__name__, 127
        (OUTPUT / f'{name}.log').write_text(text.replace(secret, '[REDACTED]'), encoding='utf-8')
        gates.append({'gate': name, 'exit_code': code, 'passed': code == 0,
                      'elapsed_seconds': time.perf_counter() - start,
                      'log': f'artifacts/container/{name}.log'})
        save()
        if code:
            raise RuntimeError(f'{name} failed; see artifacts/container/{name}.log')

    try:
        execute('compose-contract', compose + ['config', '--quiet'])
        execute('image-build', compose + ['build'])
        execute('runtime-ocr-image', compose + [
            'run', '--rm', '--no-deps', '-e', 'OCR_BACKEND=tesseract',
            'api', 'python', '-m', 'app.ops.check_ocr',
        ], timeout=120)
        execute('database-and-redis', compose + ['up', '-d', '--wait', 'postgres', 'redis'])
        try:
            execute('backend-integration', compose + ['run', '--rm', 'checks'])
        finally:
            record_backend_subgates()
        execute('runtime-start', compose + ['up', '-d', 'api', 'worker', 'scheduler', 'web'])
        start = time.monotonic()
        ready = False
        readiness_snapshot: dict[str, object] | None = None
        web_status: int | None = None
        while time.monotonic() - start < 180:
            try:
                with urlopen('http://localhost:18000/health/ready', timeout=3) as response:
                    readiness_snapshot = json.load(response)
                dependencies = readiness_snapshot.get('dependencies', {})
                if (
                    readiness_snapshot.get('status') == 'ready'
                    and isinstance(dependencies, dict)
                    and all(dependencies.values())
                ):
                    with urlopen('http://localhost:13000', timeout=3) as response:
                        web_status = response.status
                        ready = response.status == 200
                    if ready:
                        break
            except HTTPError as error:
                try:
                    candidate = json.load(error)
                    if isinstance(candidate, dict):
                        readiness_snapshot = candidate
                except (ValueError, OSError):
                    pass
            except (URLError, TimeoutError, ConnectionError, ValueError):
                pass
            time.sleep(2)
        report['readiness_snapshot'] = readiness_snapshot
        gates.append({'gate': 'full-readiness', 'passed': ready, 'web_status': web_status,
                      'elapsed_seconds': time.monotonic() - start})
        save()
        if not ready:
            raise RuntimeError(
                'Full readiness failed (DB, migration, Redis, worker, scheduler, storage)'
            )
        execute('web-install', ['npm', 'ci'], ROOT / 'apps/web')
        for script in ['test', 'typecheck', 'lint']:
            execute('web-' + script, ['npm', 'run', script], ROOT / 'apps/web')
        browser_args = ['node', 'node_modules/playwright/cli.js', 'install']
        if sys.platform.startswith('linux'):
            browser_args.append('--with-deps')
        execute('browser-install', browser_args + ['chromium'], ROOT / 'apps/web')
        execute('real-lifecycle-e2e', ['node', 'e2e/lifecycle.mjs'], ROOT / 'apps/web')
        execute('pipeline-demo-e2e', ['node', 'e2e/pipeline.mjs'], ROOT / 'apps/web')
        # Stop cron before isolated ingestion load; only the benchmark's ARQ worker runs.
        execute('pause-background-jobs', compose + ['stop', 'worker', 'scheduler'])
        execute('queue-scale', compose + ['run', '--rm', 'checks', 'python',
            'scripts/seed_scale.py',
                '--records', str(args.scale_records), '--output',
                    '/workspace/artifacts/container/queue-load.json'])
        execute('query-plans', compose + ['run', '--rm', 'checks', 'python',
            'scripts/query_plans.py',
                '--output', '/workspace/artifacts/container/query-plans.json'])
        execute('http-load', compose + ['run', '--rm', 'checks', 'python', 'scripts/load_test.py',
                '--mode', 'service', '--requests', '50', '--concurrency', '5', '--base-url',
                'http://api:8000', '--output', '/workspace/artifacts/container/http-load.json'])
        execute('backfill-scale', compose + ['run', '--rm', 'checks', 'python',
                'scripts/backfill_benchmark.py', '--records', str(args.backfill_records),
                '--page-size', '100', '--first-batch-pages', '5', '--output',
                '/workspace/artifacts/container/backfill.json'])
        publish_public_measurements()
        execute('resume-background-jobs', compose + ['start', 'worker', 'scheduler'])
        report.update(status='passed', passed=True, finished_at=datetime.now(UTC).isoformat())
        save()
    except RuntimeError as error:
        report.update(status='failed', error=str(error))
        save()
        print(str(error))
        raise SystemExit(1) from None
    finally:
        try:
            result = subprocess.run(compose + ['logs', '--no-color'], cwd=ROOT, env=environment,
                                    capture_output=True, text=True, encoding='utf-8',
                                        errors='replace',
                                    timeout=30, check=False)
            (OUTPUT / 'services.log').write_text(result.stdout.replace(secret, '[REDACTED]'),
                encoding='utf-8')
            if not args.keep_running:
                subprocess.run(compose + ['down', '--volumes', '--remove-orphans'], cwd=ROOT,
                               env=environment, check=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            print('Automatic cleanup was not completed; see the recorded isolated project name.')
    print('Container gate passed. Evidence: artifacts/container/release-gate.json')
    if args.keep_running:
        print('Isolated demo: http://localhost:13000. Operator secret is not printed or stored.')


if __name__ == '__main__':
    main()
