from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--integration', action='store_true',
                        help='Runs DB/Redis failure tests on a dedicated test database')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/failures/http.json')
    args = parser.parse_args()
    from app.evaluation.failure import http_drills
    from app.evaluation.provenance import environment, write_artifact
    result = asyncio.run(http_drills())
    result['environment'] = environment()
    exit_code = 0 if all(row['passed'] for row in result['cases']) else 1
    if args.integration:
        selected = [
            'tests/workers/test_jobs.py', 'tests/notifications/test_delivery.py',
            'tests/api/test_admin.py', 'tests/documents/test_reconciliation.py',
        ]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        log = args.output.with_suffix('.log')
        with log.open('w', encoding='utf-8') as out:
            process = subprocess.run(
                [sys.executable, '-m', 'pytest', *selected, '-q',
                 f'--junitxml={args.output.with_suffix(".xml").resolve()}'],
                cwd=ROOT / 'apps/api', stdout=out, stderr=subprocess.STDOUT, check=False)
        result['integration'] = {'exit_code': process.returncode, 'log': log.name,
                                  'status': 'passed' if process.returncode == 0 else 'failed'}
        exit_code = process.returncode or exit_code
    write_artifact(args.output, result, 'ProcureDelta failure drills')
    print(json.dumps({'artifact': str(args.output), 'exit_code': exit_code}))
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
