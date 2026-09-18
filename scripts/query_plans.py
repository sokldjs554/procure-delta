"""Measure a candidate keyset-order index in a ROLLBACK-only isolated DB transaction.

Does not install a permanent index or claim a speedup without the returned plans.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))
QUERY = """SELECT id, title, published_at FROM opportunities
ORDER BY coalesce(published_at, '1970-01-01T00:00:00Z'::timestamptz) DESC, id DESC LIMIT 20"""
CANDIDATE = """CREATE INDEX procure_delta_bench_order_candidate ON opportunities
((coalesce(published_at, '1970-01-01T00:00:00Z'::timestamptz)) DESC, id DESC)"""


async def measure(url: str) -> dict[str, Any]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.evaluation.performance import require_benchmark_database
    from app.evaluation.provenance import environment
    require_benchmark_database(url)
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                count = int((await connection.execute(
                    text('SELECT count(*) FROM opportunities')
                )).scalar_one())
                if count < 1000:
                    raise ValueError('seed at least 1,000 synthetic opportunities first')
                await connection.execute(text('SET LOCAL statement_timeout = 60000'))
                await connection.execute(text('ANALYZE opportunities'))
                version = str((await connection.execute(text('SELECT version()'))).scalar_one())
                before = [(await connection.execute(text(
                    'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + QUERY))).scalar_one()
                    for _ in range(5)]
                await connection.execute(text(CANDIDATE))
                after = [(await connection.execute(text(
                    'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + QUERY))).scalar_one()
                    for _ in range(5)]
                return {'scope': 'real_postgresql_explain', 'environment': environment(),
                        'database_version': version, 'rows': count, 'query': QUERY,
                        'candidate_ddl': CANDIDATE, 'before': before, 'after': after,
                        'candidate_adopted': False, 'candidate_rolled_back': True,
                        'caution': (
                            'Fixed order and warmed caches; repeat across fresh runs before adopting.'
                        )}
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path,
        default=ROOT / 'artifacts/performance/query-plans.json')
    args = parser.parse_args()
    from app.evaluation.provenance import write_artifact
    result = asyncio.run(measure(os.environ['BENCH_DATABASE_URL']))
    write_artifact(args.output, result, 'PostgreSQL candidate index experiment')
    print(args.output)


if __name__ == '__main__':
    main()
