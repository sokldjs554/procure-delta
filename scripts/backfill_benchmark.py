"""Measure the real paginated polling/checkpoint/resume path on the isolated benchmark DB."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=2000)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--first-batch-pages", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/container/backfill.json",
    )
    args = parser.parse_args()

    from app.evaluation.integration import backfill_load
    from app.evaluation.provenance import write_artifact

    result = asyncio.run(
        backfill_load(
            args.records,
            page_size=args.page_size,
            first_batch_pages=args.first_batch_pages,
        )
    )
    write_artifact(args.output, result, "Synthetic paginated backfill benchmark")
    if not result["successful"]:
        raise SystemExit("Backfill benchmark failed; inspect the artifact.")
    print(args.output)


if __name__ == "__main__":
    main()
