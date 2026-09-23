"""Offline by default. Hosted network requests require an explicit command-line opt-in."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/evaluation/local.json')
    parser.add_argument('--with-ocr', action='store_true')
    parser.add_argument('--allow-hosted', action='store_true',
                        help='Allows paid/network calls using configured EXTRACTION_* variables')
    parser.add_argument('--publish', action='store_true',
        help='Copy this measured artifact to the public evaluation panel')
    args = parser.parse_args()
    from app.evaluation.provenance import write_artifact
    from app.evaluation.runner import run_evaluation
    hosted = None
    if args.allow_hosted:
        from app.config import get_settings
        from app.extraction.hosted import configured_extractor
        settings = get_settings()
        if settings.extraction_mode != 'hosted':
            parser.error('--allow-hosted requires EXTRACTION_MODE=hosted')
        hosted = configured_extractor(settings)
    result = asyncio.run(run_evaluation(ROOT, with_ocr=args.with_ocr, hosted=hosted))
    write_artifact(args.output, result, 'ProcureDelta synthetic evaluation')
    if hosted is not None:
        for name in ('hosted_all', 'hosted_gated'):
            route = result['extraction_routes'][name]
            # Only the runner's bounded diagnostics; no raw error bodies or exception messages.
            errors = [
                {key: row[key] for key in ('id', 'error_type', 'http_status',
                                          'provider_error_type', 'provider_hint')}
                for row in route['rows'] if row['error_type'] is not None
            ]
            print(json.dumps({'route': name, 'status': route['status'],
                              'execution_errors': route['execution_errors'], 'errors': errors},
                             ensure_ascii=False))
    if args.publish:
        if hosted is not None:
            from app.evaluation.hosted_artifact import validate_hosted_artifact
            validate_hosted_artifact(result)
        import shutil
        target = ROOT / 'apps/api/app/evaluation/results/local.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.output, target)
    print(f'Evaluation artifact: {args.output}')
    print('Synthetic regression only; see per-metric support and unrun external routes.')


if __name__ == '__main__':
    main()
