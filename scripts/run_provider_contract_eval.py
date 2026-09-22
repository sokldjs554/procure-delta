"""Measure the hosted HTTP contract without pretending to measure an external model."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic_core import to_jsonable_python

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

from app.evaluation.provenance import load_dataset
from app.evaluation.runner import extraction_eval, hosted_optimization
from app.extraction.hosted import HostedExtractor
from app.extraction.schemas import DocumentBundle
from app.extraction.validation import labeled_claims
from app.sources.http import ResilientHttpClient

PROMPT_TOKENS_PER_CALL = 100
COMPLETION_TOKENS_PER_CALL = 20


def _stub_output(document: DocumentBundle) -> dict[str, Any]:
    output: dict[str, Any] = {"schema_version": "1", "evidence": {}}
    evidence = output["evidence"]
    assert isinstance(evidence, dict)
    for page in document.pages:
        for line in page.text.splitlines():
            claims = labeled_claims(line)
            for field, value in claims.items():
                output.setdefault(field, to_jsonable_python(value))
                references = evidence.setdefault(field, [])
                assert isinstance(references, list)
                references.append(
                    {
                        "attachment_sha256": page.attachment_sha256,
                        "page_number": page.page_number,
                        "quote": line.strip(),
                    }
                )
    return output


async def run(output: Path) -> dict[str, Any]:
    data, dataset_hash = load_dataset(ROOT / "data/eval")
    idempotency_keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        idempotency_keys.append(request.headers["Idempotency-Key"])
        payload = json.loads(request.content)
        messages = payload["messages"]
        document = DocumentBundle.model_validate_json(messages[1]["content"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                _stub_output(document),
                                ensure_ascii=False,
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": PROMPT_TOKENS_PER_CALL,
                    "completion_tokens": COMPLETION_TOKENS_PER_CALL,
                },
            },
        )

    async with ResilientHttpClient(
        transport=httpx.MockTransport(handler),
        backoff_base_seconds=0,
    ) as client:
        extractor = HostedExtractor(
            endpoint="https://provider-contract.invalid/v1/chat/completions",
            provider="provider-contract-stub",
            model="contract-v1",
            client=client,
        )
        all_route = await extraction_eval(data["extraction_cases"], extractor)
        gated_route = await extraction_eval(
            data["extraction_cases"],
            extractor,
            gated=True,
        )

    optimization = hosted_optimization(all_route, gated_route)
    result: dict[str, Any] = {
        "schema_version": 1,
        "suite": "provider-contract-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "model_quality_measured": False,
        "external_network": False,
        "transport": "httpx.MockTransport",
        "dataset_sha256": dataset_hash,
        "usage_basis": (
            "Synthetic provider-reported usage counters; not tokenizer output or billing."
        ),
        "routes": {
            "all": all_route,
            "gated": gated_route,
        },
        "optimization": optimization,
        "http_requests": len(idempotency_keys),
        "unique_idempotency_keys": len(set(idempotency_keys)),
        "idempotency_reuse_verified": (
            len(idempotency_keys) == 15 and len(set(idempotency_keys)) == 10
        ),
        "limitation": (
            "Exercises the production HTTP/JSON extraction contract with a deterministic "
            "provider stub. It does not measure external LLM accuracy, latency, tokens, "
            "pricing, availability, or provider behavior."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def _assert_contract(result: dict[str, Any]) -> None:
    routes = result["routes"]
    all_route = routes["all"]
    gated_route = routes["gated"]
    optimization = result["optimization"]

    if all_route["hosted_calls"] != 10 or gated_route["hosted_calls"] != 5:
        raise SystemExit("provider contract call gate did not reduce 10 calls to 5")
    if all_route["prompt_tokens"] != 1000 or gated_route["prompt_tokens"] != 500:
        raise SystemExit("provider contract prompt usage aggregation changed")
    if all_route["completion_tokens"] != 200 or gated_route["completion_tokens"] != 100:
        raise SystemExit("provider contract completion usage aggregation changed")
    if all_route["field_accuracy"] != 1.0 or gated_route["field_accuracy"] != 1.0:
        raise SystemExit("provider contract structured-field regression failed")
    if all_route["reported_cost_per_document"] is not None:
        raise SystemExit("provider contract must not invent provider billing")
    if gated_route["reported_cost_per_document"] is not None:
        raise SystemExit("provider contract must not invent gated provider billing")
    if optimization["call_reduction_rate"] != 0.5:
        raise SystemExit("provider contract call reduction must be 50%")
    if optimization["token_reduction_rate"] != 0.5:
        raise SystemExit("provider contract token reduction must be 50%")
    if optimization["reported_cost_reduction_rate"] is not None:
        raise SystemExit("provider contract must not report monetary cost reduction")
    if result["idempotency_reuse_verified"] is not True:
        raise SystemExit("provider contract idempotency reuse was not verified")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/evaluation/provider-contract.json",
    )
    args = parser.parse_args()
    result = asyncio.run(run(args.output))
    _assert_contract(result)
    print(f"Provider contract artifact: {args.output}")
    print("calls=10->5 token-counters=1200->600 external-model-quality=not-measured")


if __name__ == "__main__":
    main()
