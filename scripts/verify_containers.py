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
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'artifacts/container'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--keep-running', action='store_true')
    parser.add_argument('--scale-records', type=int, default=1000)
    args = parser.parse_args()
    if not 1000 <= args.scale_records <= 50000:
        parser.error('--scale-records must be between 1000 and 50000')
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
            except (URLError, TimeoutError, ValueError):
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
