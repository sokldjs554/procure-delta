"""Explicit, bounded Claude connectivity diagnosis; never a quality measurement."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

# Only these public protocol terms can leave an upstream error. Unknown words,
# values, URLs, quoted documents and the order of the original sentence are lost.
SAFE_TERMS = frozenset({
    "api", "authentication", "authorization", "bearer", "oauth", "token", "key", "invalid",
    "expired", "revoked", "missing", "required", "unsupported", "not", "supported", "allowed",
    "forbidden", "permission", "access", "denied", "disabled", "organization", "workspace",
    "anthropic-workspace-id", "anthropic-version", "version", "header", "model", "models",
    "max_tokens", "max_completion_tokens", "messages", "role", "system", "user", "assistant",
    "response_format", "json_object", "schema", "type", "parameter", "field", "value", "input",
    "output", "length", "maximum", "minimum", "exceeds", "limit", "rate", "quota", "billing",
    "credit", "credits", "balance", "low", "insufficient", "payment", "prepaid", "account",
    "active", "unavailable", "request", "malformed", "unexpected", "extra", "content", "stream",
    "temperature", "top_p", "idempotency-key", "date", "valid", "enabled", "subscription", "console",
})
SAFE_PARAMS = frozenset({"model", "max_tokens", "max_completion_tokens", "messages",
                         "response_format", "anthropic-version", "anthropic-workspace-id"})
SAFE_CODES = frozenset({"invalid_api_key", "insufficient_quota", "unsupported_parameter",
                        "invalid_parameter", "model_not_found", "missing_required_parameter"})


def response_summary(response: httpx.Response, secret: str) -> dict[str, Any]:
    from app.evaluation.runner import SAFE_PROVIDER_ERROR_TYPES

    result: dict[str, Any] = {"http_status": response.status_code}
    try:
        envelope = response.json()
    except ValueError:
        return {**result, "response_shape": "non_json"}
    if not isinstance(envelope, dict):
        return {**result, "response_shape": "non_object"}
    if response.is_success:
        usage = envelope.get("usage")
        if isinstance(usage, dict):
            for name in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
                value = usage.get(name)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    result[name] = value
        return result
    detail = envelope.get("error")
    if not isinstance(detail, dict):
        return {**result, "response_shape": "unknown_error"}
    for source, target, allowed in (
        ("type", "provider_error_type", SAFE_PROVIDER_ERROR_TYPES),
        ("code", "provider_error_code", SAFE_CODES),
        ("param", "provider_error_param", SAFE_PARAMS),
    ):
        value = detail.get(source)
        result[target] = value if isinstance(value, str) and value in allowed else None
    message = detail.get("message")
    result["message_terms"] = []
    if isinstance(message, str) and len(message) <= 8192:
        # Even if a credential contains a protocol word, remove the exact value first.
        message = message.replace(secret, "[redacted]") if secret else message
        terms = set(re.findall(r"[a-z_][a-z0-9_-]*", message.lower()))
        result["message_terms"] = sorted(terms & SAFE_TERMS)
    return result


async def run_probe(
    root: Path, *, endpoint: str, provider: str, model: str, api_key: str,
    max_completion_tokens: int, transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    from app.evaluation.provenance import load_dataset
    from app.evaluation.runner import bundle
    from app.extraction.hosted import HostedExtractor
    from app.extraction.validation import validate_extraction
    from app.sources.http import ResilientHttpClient

    result: dict[str, Any] = {"schema_version": 1, "quality_evaluated": False,
        "status": "blocked", "probes": {}, "request_limit": 3}
    if endpoint != "https://api.anthropic.com/v1/chat/completions" or provider != "anthropic":
        return {**result, "reason": "probe_requires_official_claude_compatibility_endpoint"}
    if not api_key:
        return {**result, "reason": "missing_credential"}
    if not api_key.isascii() or any(c.isspace() for c in api_key):
        return {**result, "reason": "credential_contains_whitespace_or_non_ascii"}
    if not api_key.startswith("sk-ant-api"):
        return {**result, "reason": "console_api_credential_required"}
    if not 1 <= max_completion_tokens <= 32768 or not model:
        return {**result, "reason": "invalid_probe_configuration"}

    data, dataset_hash = load_dataset(root / "data/eval")
    result["dataset_sha256"] = dataset_hash
    headers = {"Authorization": f"Bearer {api_key}"}
    message = [{"role": "user", "content": "Reply with OK."}]
    probes = result["probes"]
    async with httpx.AsyncClient(
        transport=transport, follow_redirects=False,
        timeout=httpx.Timeout(20, connect=5),
    ) as client:
        for name, url, body, extra_headers in (
            ("native_minimal", "https://api.anthropic.com/v1/messages",
             {"model": model, "max_tokens": 16, "messages": message},
             {"anthropic-version": "2023-06-01"}),
            ("compatible_minimal", endpoint,
             {"model": model, "max_completion_tokens": 16, "messages": message}, {}),
        ):
            try:
                async with asyncio.timeout(25):
                    response = await client.post(url, headers={**headers, **extra_headers},
                                                 json=body)
                probes[name] = response_summary(response, api_key)
            except (TimeoutError, httpx.TimeoutException):
                probes[name] = {"http_status": None, "transport_error": "timeout"}
            except httpx.HTTPError:
                probes[name] = {"http_status": None, "transport_error": "http_transport_error"}

    probes["project_extraction"] = {"status": "not_run"}
    compat_status = probes["compatible_minimal"].get("http_status")
    if isinstance(compat_status, int) and 200 <= compat_status < 300:
        document = bundle(data["extraction_cases"][0]["text"])
        async with ResilientHttpClient(transport=transport, max_attempts=1) as client:
            extractor = HostedExtractor(endpoint=endpoint, provider=provider, model=model,
                api_key=api_key, client=client, max_completion_tokens=max_completion_tokens)
            try:
                proposal = await extractor.extract(document)
                probes["project_extraction"] = {
                    "status": "received", "http_status": 200,
                    "grounded_valid": validate_extraction(proposal, document).valid,
                    "prompt_tokens": proposal.prompt_tokens,
                    "completion_tokens": proposal.completion_tokens,
                }
            except httpx.HTTPStatusError as error:
                probes["project_extraction"] = response_summary(error.response, api_key)
            except (TimeoutError, httpx.TimeoutException):
                probes["project_extraction"] = {"transport_error": "timeout"}
            except httpx.HTTPError:
                probes["project_extraction"] = {"transport_error": "http_transport_error"}

    result["status"] = "completed" if all(
        isinstance(p.get("http_status"), int) and 200 <= p["http_status"] < 300
        for p in probes.values()
    ) else "failed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-hosted", action="store_true")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "artifacts/evaluation/hosted-probe.json")
    args = parser.parse_args()
    if not args.allow_hosted:
        parser.error("network diagnosis requires --allow-hosted")
    try:
        limit = int(os.getenv("EXTRACTION_MAX_COMPLETION_TOKENS", "4096"))
    except ValueError:
        parser.error("invalid completion token limit")
    try:
        result = asyncio.run(run_probe(ROOT,
            endpoint=os.getenv("EXTRACTION_ENDPOINT", ""),
            provider=os.getenv("EXTRACTION_PROVIDER", ""),
            model=os.getenv("EXTRACTION_MODEL", ""),
            api_key=os.getenv("EXTRACTION_API_KEY", ""), max_completion_tokens=limit))
    except Exception:  # noqa: BLE001 -- final CLI boundary must not echo upstream secrets
        # Do not let a diagnostic script print exception messages or a traceback
        # containing echoed credentials. Expected provider errors are handled above.
        result = {"status": "failed", "quality_evaluated": False,
                  "reason": "unexpected_probe_failure"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
