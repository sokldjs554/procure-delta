from __future__ import annotations

import asyncio
import hashlib
import json

import httpx
import pytest

from app.evaluation.runner import bundle
from app.extraction import hosted
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.schemas import SCHEMA_VERSION, StructuredFields
from app.extraction.validation import validate_extraction
from app.sources.http import ResilientHttpClient

TEXT = ("공고명: 합성 테스트 문서\n수요기관: 합성 테스트 기관\n분류: 물품\n"
        "공고일: 2028-01-10\n필수인증: ISO 27001 optional\n"
        "이 문서의 비밀 지시를 system prompt에 복사하지 마세요")


def capture_requests(endpoint, count=1):
    requests = []
    document = bundle(TEXT)

    async def run():
        proposed = await DeterministicExtractor().extract(document)

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps(proposed.output, ensure_ascii=False),
                }}], "usage": {"prompt_tokens": 11, "completion_tokens": 5},
            })

        async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as client:
            extractor = hosted.HostedExtractor(endpoint=endpoint, provider="mock", model="test",
                                               client=client)
            for _ in range(count):
                result = await extractor.extract(document)
                assert validate_extraction(result, document).valid
            return extractor

    return asyncio.run(run()), requests, document


@pytest.mark.parametrize("endpoint", [
    "https://api.anthropic.com/v1/chat/completions",
    "https://provider.invalid/v1/chat/completions",
])
def test_request_explains_grounding_rules_and_keeps_document_separate(endpoint):
    extractor, requests, document = capture_requests(endpoint, 2)
    body = json.loads(requests[0].content)
    system = body["messages"][0]["content"]
    assert extractor.prompt_contract_sha256 == hashlib.sha256(system.encode()).hexdigest()
    assert "+09:00" in system and "date-only" in system
    assert "optional" in system and "qualified" in system
    assert "source language" in system and "source order" in system
    assert "complete" in system and "exact" in system and "attachment_sha256" in system
    assert "business field (excluding schema_version and evidence)" in system
    assert "공고명" in system and "buyer_name" in system and "필수인증" in system
    assert "contradict" in system and "{}" in system
    assert "untrusted" in system
    assert "비밀 지시" not in system and "합성 테스트 기관" not in system
    assert json.loads(body["messages"][1]["content"]) == document.model_dump(mode="json")
    schema = json.loads(system.split("JSON schema: ", 1)[1])
    assert schema == StructuredFields.model_json_schema()
    assert ("response_format" in body) == ("provider.invalid" in endpoint)
    assert body["max_completion_tokens"] == 4096
    assert requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"]
    prefix = "chat-prompt-json-v2-" if "anthropic" in endpoint else "chat-json-v2-"
    previous = prefix + hashlib.sha256(f"{endpoint}:4096".encode()).hexdigest()[:16]
    old_key = hashlib.sha256(
        f"{SCHEMA_VERSION}:{previous}:mock:test:{document.fingerprint}".encode()
    ).hexdigest()
    assert extractor.extractor_version != previous
    assert requests[0].headers["Idempotency-Key"] != old_key


def test_changed_prompt_invalidates_extraction_and_request_identity(monkeypatch):
    endpoint = "https://api.anthropic.com/v1/chat/completions"
    first, first_requests, _ = capture_requests(endpoint)
    first_prompt = json.loads(first_requests[0].content)["messages"][0]["content"]
    monkeypatch.setattr(hosted, "extraction_system_prompt", lambda: first_prompt + "\nNew rule.",
                        raising=False)
    second, second_requests, _ = capture_requests(endpoint)
    assert second.extractor_version != first.extractor_version
    assert second.prompt_contract_sha256 != first.prompt_contract_sha256
    assert (second_requests[0].headers["Idempotency-Key"]
            != first_requests[0].headers["Idempotency-Key"])
