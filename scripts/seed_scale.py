"""Populate an isolated benchmark DB through the real Redis/ARQ ingest path."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--records', type=int, default=5000)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/performance/seed.json')
    args = parser.parse_args()
    from app.evaluation.integration import prepare_scale_source, queue_load
    from app.evaluation.provenance import write_artifact
    result = asyncio.run(queue_load(args.records))
    if result['successful']:
        result['read_setup'] = asyncio.run(prepare_scale_source(result['source_code']))
    write_artifact(args.output, result, 'Synthetic real-service scale seed')
    if not result['successful']:
        raise SystemExit('Ingest errors occurred; inspect the artifact before benchmarking.')
    print(args.output)


if __name__ == '__main__':
    main()
