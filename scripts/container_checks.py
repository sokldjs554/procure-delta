"""Container-side verification; each command's real exit code is recorded."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'artifacts/container'


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    commands = [
        ('backend-lint', ['ruff', 'check', '.'], ROOT / 'apps/api'),
        ('backend-types', ['mypy', 'app'], ROOT / 'apps/api'),
        ('backend-db-isolation-regression', [
            sys.executable, '-m', 'pytest', '-q',
            'tests/db/test_schema.py',
            'tests/demo/test_seed_integration.py',
            'tests/domain/test_versioning.py',
            'tests/ranking/test_eligibility.py',
            'tests/sources/test_koneps_mapping.py',
            'tests/test_database_isolation.py',
        ], ROOT / 'apps/api'),
        ('backend-tests', [sys.executable, '-m', 'pytest', '-q',
                           f'--junitxml={OUTPUT / "pytest.xml"}'], ROOT / 'apps/api'),
        ('source-contracts', [sys.executable, '-m', 'unittest', 'discover', '-s',
            'contract_tests', '-v'], ROOT / 'apps/api'),
        ('evaluation', [sys.executable, 'scripts/run_eval.py', '--output',
            str(OUTPUT / 'evaluation.json')], ROOT),
        ('evaluation-korean-ocr', [
            sys.executable, 'scripts/run_korean_ocr_eval.py', '--output',
            str(OUTPUT / 'korean-ocr.json')
        ], ROOT),
        ('fault-drill', [sys.executable, 'scripts/failure_drill.py', '--integration',
                         '--output', str(OUTPUT / 'fault-drill.json')], ROOT),
    ]
    rows = []
    for name, command, cwd in commands:
        with (OUTPUT / f'{name}.log').open('w', encoding='utf-8') as handle:
            process = subprocess.run(command, cwd=cwd, stdout=handle,
                                     stderr=subprocess.STDOUT, check=False)
        rows.append({'gate': name, 'exit_code': process.returncode,
                     'passed': process.returncode == 0})
        (OUTPUT / 'checks.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
        print(name, 'PASS' if process.returncode == 0 else 'FAIL', flush=True)
    raise SystemExit(0 if all(row['passed'] for row in rows) else 1)


if __name__ == '__main__':
    main()
