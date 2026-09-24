from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.evaluation.hosted_artifact import HostedEvaluationError, validate_hosted_artifact
from app.evaluation.runner import extraction_eval, hosted_optimization
from app.extraction.hosted import HostedExtractor
from app.sources.http import ResilientHttpClient

PRIVATE = "private-model-reply-must-not-be-published"
CASE = {"id": "rejected", "text": "Unsupported prose.",
        "expected_valid": False, "expected_fields": {}}


def evaluate(content, usage):
    async def run():
        async with ResilientHttpClient(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}],
                       "usage": usage},
        ))) as client:
            return await extraction_eval([CASE], HostedExtractor(
                endpoint="https://api.anthropic.com/v1/chat/completions",
                provider="anthropic", model="test", client=client,
            ))
    return asyncio.run(run())


def artifact(route):
    return {"schema_version": 1, "provenance": {"synthetic": True},
            "extraction_routes": {"hosted_all": route, "hosted_gated": route},
            "hosted_optimization": hosted_optimization(route, route)}


@pytest.mark.parametrize("content,stage,status", [
    (PRIVATE, "response", "invalid_json"),
    (json.dumps({PRIVATE: PRIVATE}), "schema", "parsed"),
    (json.dumps({"schema_version": "1", "title": PRIVATE, "buyer_name": PRIVATE,
                 "procurement_type": "goods", "evidence": {}}), "grounding", "parsed"),
])
def test_usage_and_rejection_stage_reach_artifact_without_model_text(content, stage, status):
    route = evaluate(content, {"prompt_tokens": 12, "completion_tokens": 4})
    assert route["prompt_tokens"] == 12 and route["completion_tokens"] == 4
    assert route["execution_errors"] == 0
    row = route["rows"][0]
    assert row["valid"] is False
    assert row["rejection_stage"] == stage
    assert row["prompt_tokens"] == 12 and row["completion_tokens"] == 4
    assert row["response_diagnostics"]["status"] == status
    assert row["response_diagnostics"]["http_status"] == 200
    if stage == "schema":
        assert "buyer_name" in row["schema_error_fields"]
        assert "unknown" in row["schema_error_fields"]
    assert PRIVATE not in json.dumps(route)
    # A measured rejection still spends tokens; passing metrics validation does
    # not turn the rejected answer into a trusted extraction.
    assert validate_hosted_artifact(artifact(route))["all_tokens"] == 16
    assert route["grounded_accepted_documents"] == 0


def test_missing_usage_still_blocks_publishing_without_invented_zero():
    route = evaluate("{}", {"prompt_tokens": 12})
    assert route["prompt_tokens"] == 12 and route["completion_tokens"] is None
    assert route["rows"][0]["response_diagnostics"]["usage_status"] == "partial"
    with pytest.raises(HostedEvaluationError, match="completion tokens are not measured"):
        validate_hosted_artifact(artifact(route))
