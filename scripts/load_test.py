from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))


def main() -> None:
    parser = argparse.ArgumentParser(description='Explicitly separate CPU, HTTP and real ARQ load.')
    parser.add_argument('--mode', choices=['cpu', 'service', 'queue'], default='cpu')
    parser.add_argument('--records', type=int, default=50000)
    parser.add_argument('--requests', type=int, default=100)
    parser.add_argument('--concurrency', type=int, default=5)
    parser.add_argument('--base-url', default='http://localhost:8000')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/performance/cpu.json')
    args = parser.parse_args()
    from app.evaluation.provenance import write_artifact
    if args.mode == 'cpu':
        from app.evaluation.performance import cpu_benchmark
        result = cpu_benchmark(args.records)
    elif args.mode == 'service':
        from app.evaluation.integration import service_load
        result = asyncio.run(service_load(args.base_url, args.requests, args.concurrency))
    else:
        from app.evaluation.integration import queue_load
        result = asyncio.run(queue_load(args.records))
    write_artifact(args.output, result, f'ProcureDelta {args.mode} benchmark')
    print(f'Result: {args.output}')
    if result.get('successful') is False:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
