"""Read-only, bounded KONEPS smoke check. No DB writes or document downloads."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from app.sources.http import ResilientHttpClient
from app.sources.koneps import BASE_URL, OPERATION, KonepsSourceAdapter, map_payload


def _bounded_integer(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 10:
        raise argparse.ArgumentTypeError("expected an integer between 1 and 10")
    return number


async def check_pages(
    adapter: KonepsSourceAdapter, *, mode: str, max_pages: int
) -> dict[str, Any]:
    if mode not in {"synthetic_contract", "live"} or not 1 <= max_pages <= 10:
        raise ValueError("invalid smoke configuration")
    cursor = None
    payload_hash = hashlib.sha256()
    count = 0
    pages = 0
    complete = False
    for _ in range(max_pages):
        page = await adapter.discover(cursor)
        pages += 1
        for record in page.records:
            # Check mapping without modifying or persisting the original record.
            before = json.dumps(dict(record.raw_payload), ensure_ascii=False, sort_keys=True)
            mapped = map_payload(record.raw_payload, record.source_record_id)
            if not mapped.get("title") or not mapped.get("buyer_name"):
                raise ValueError("required mapped field missing")
            after = json.dumps(dict(record.raw_payload), ensure_ascii=False, sort_keys=True)
            if before != after:
                raise ValueError("mapping mutated upstream payload")
            payload_hash.update(before.encode("utf-8"))
            payload_hash.update(b"\x00")
            count += 1
        cursor = page.next_cursor
        if cursor is None or json.loads(cursor)["mode"] == "done":
            complete = True
            break
    return {
        "mode": mode,
        "live_verified": mode == "live",
        "scope": "services_tender_and_observed_revisions_only",
        "endpoint": f"{BASE_URL}/{OPERATION}",
        "pages_checked": pages,
        "records_checked": count,
        "payload_sha256": payload_hash.hexdigest(),
        "window_complete": complete,
        "database_written": False,
        "attachments_downloaded": False,
        "note": "Counts are processed rows, not a unique-dataset size or accuracy measurement.",
    }


async def _run(live: bool, max_pages: int) -> dict[str, Any]:
    if live:
        key = os.environ.get("KONEPS_SERVICE_KEY", "").strip()
        if not key:
            raise ValueError("KONEPS_SERVICE_KEY is required for --live")
        async with ResilientHttpClient() as client:
            return await check_pages(
                KonepsSourceAdapter(service_key=key, client=client),
                mode="live", max_pages=max_pages,
            )
    fixture = Path(__file__).with_name("fixtures") / "koneps_services_synthetic.json"
    body = json.loads(fixture.read_text(encoding="utf-8"))
    async with ResilientHttpClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=body)
    )) as client:
        return await check_pages(
            KonepsSourceAdapter(service_key="synthetic-contract-key", client=client),
            mode="synthetic_contract", max_pages=1,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fixture", action="store_true", help="Offline synthetic contract (default)")
    mode.add_argument("--live", action="store_true", help="Explicitly call the public API")
    parser.add_argument("--max-pages", type=_bounded_integer, default=2)
    arguments = parser.parse_args(argv)
    if arguments.live and not os.environ.get("KONEPS_SERVICE_KEY", "").strip():
        print("KONEPS_SERVICE_KEY is required for --live; no request was sent.", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(_run(arguments.live, arguments.max_pages))
    except Exception as error:
        # No exception message/body/request URL: upstream errors can echo the key.
        print(json.dumps({"status": "failed", "error_class": type(error).__name__,
                          "live_verified": False}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
