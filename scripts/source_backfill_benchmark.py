"""Measure bounded paginated source discovery against the isolated benchmark database."""
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
    parser.add_argument('--page-size', type=int, default=100)
    parser.add_argument('--page-budget', type=int, default=10)
    parser.add_argument(
        '--output',
        type=Path,
        default=ROOT / 'artifacts/performance/source-backfill.json',
    )
    args = parser.parse_args()

    from app.evaluation.integration import source_backfill_load
    from app.evaluation.provenance import write_artifact

    result = asyncio.run(
        source_backfill_load(
            args.records,
            page_size=args.page_size,
            page_budget=args.page_budget,
        )
    )
    write_artifact(args.output, result, 'Synthetic paginated source backfill')
    if not result['successful']:
        raise SystemExit('Source backfill benchmark failed; inspect the artifact.')
    print(args.output)


if __name__ == '__main__':
    main()
