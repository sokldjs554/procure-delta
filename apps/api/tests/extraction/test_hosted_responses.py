from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.extraction.hosted import HostedExtractor
from app.extraction.validation import validate_extraction
from app.sources.http import ResilientHttpClient
from tests.extraction.test_schema_validation import bundle, proposal

PRIVATE = "private-response-sentinel"
DOCUMENT = bundle("Title: Synthetic notice")
OUTPUT = proposal("title", "Synthetic notice", "Title: Synthetic notice").output


async def extract(envelope):
    async with ResilientHttpClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope))
    ) as client:
        return await HostedExtractor(
            endpoint="https://api.anthropic.com/v1/chat/completions",
            provider="anthropic", model="test", client=client,
        ).extract(DOCUMENT)


def response(content, *, finish="stop", refusal=None, usage=None):
    return {
        "choices": [{"finish_reason": finish,
                     "message": {"content": content, "refusal": refusal}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4} if usage is None else usage,
        "estimated_cost": "0.00002",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("envelope,status", [
    (response(PRIVATE), "invalid_json"),
    (response("[]"), "non_object_json"),
    (response("{}", finish="length"), "incomplete_response"),
    (response("{}", refusal=PRIVATE), "refused"),
    (response("{}", finish=PRIVATE), "incomplete_response"),
    (response(None), "invalid_envelope"),
    ({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 4},
      "estimated_cost": "0.00002"}, "invalid_envelope"),
])
async def test_rejected_responses_keep_provider_usage_and_safe_reason(envelope, status):
    result = await extract(envelope)
    assert not validate_extraction(result, DOCUMENT).valid
    assert (result.prompt_tokens, result.completion_tokens) == (12, 4)
    assert result.estimated_cost == Decimal("0.00002")
    assert result.diagnostics.status == status
    assert result.diagnostics.http_status == 200
    assert PRIVATE not in result.diagnostics.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix,suffix,kind", [
    ("", "", "plain"),
    ("```json\n", "\n```", "json_fence"),
    (" \n```\r\n", "\r\n```\n ", "json_fence"),
])
async def test_single_json_document_or_whole_fence_preserves_grounded_claims(prefix, suffix, kind):
    result = await extract(response(prefix + json.dumps(OUTPUT) + suffix))
    assert validate_extraction(result, DOCUMENT).valid
    assert result.output == OUTPUT
    assert result.diagnostics.status == "parsed"
    assert result.diagnostics.content_format == kind
    assert result.prompt_tokens == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    'Explanation\n```json\n{}\n```',
    '```json\n{}\n```\nExplanation',
    '```json\n{}\n```\n```json\n{}\n```',
    '```json\n{"title":',
    '```json\n{"estimated_amount": NaN}\n```',
    '```json\n{"estimated_amount": 1e400}\n```',
])
async def test_prose_multiple_blocks_truncation_and_nonfinite_json_stay_rejected(content):
    result = await extract(response(content))
    assert not validate_extraction(result, DOCUMENT).valid
    assert result.diagnostics.status == "invalid_json"
    assert result.prompt_tokens == 12


@pytest.mark.asyncio
async def test_fence_does_not_bypass_evidence_validation():
    invented = {**OUTPUT, "title": "Invented claim"}
    result = await extract(response("```json\n" + json.dumps(invented) + "\n```"))
    assert result.diagnostics.status == "parsed"
    assert not validate_extraction(result, DOCUMENT).valid


@pytest.mark.asyncio
@pytest.mark.parametrize("usage,prompt,completion,state", [
    ({"prompt_tokens": True, "completion_tokens": 4}, None, 4, "partial"),
    ({"prompt_tokens": "12", "completion_tokens": 4}, None, 4, "partial"),
    ({"prompt_tokens": -1, "completion_tokens": 4}, None, 4, "partial"),
    ({"prompt_tokens": 12, "completion_tokens": 4.5}, 12, None, "partial"),
    ({"prompt_tokens": 0, "completion_tokens": 0}, 0, 0, "reported"),
    ({}, None, None, "missing"),
    ([], None, None, "missing"),
])
async def test_usage_is_never_invented_or_coerced(usage, prompt, completion, state):
    result = await extract(response(json.dumps(OUTPUT), usage=usage))
    assert validate_extraction(result, DOCUMENT).valid
    assert (result.prompt_tokens, result.completion_tokens) == (prompt, completion)
    assert result.diagnostics.usage_status == state


@pytest.mark.asyncio
async def test_invalid_reported_cost_does_not_discard_tokens_or_claims():
    envelope = response(json.dumps(OUTPUT))
    envelope["estimated_cost"] = PRIVATE
    result = await extract(envelope)
    assert validate_extraction(result, DOCUMENT).valid
    assert result.prompt_tokens == 12 and result.completion_tokens == 4
    assert result.estimated_cost is None
    assert PRIVATE not in result.diagnostics.model_dump_json()
