from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts/probe_hosted.py"
SECRET = "sk-ant-api03-private-sentinel-must-not-appear"


def module():
    assert SCRIPT.exists(), "A bounded, secret-safe hosted probe is required"
    spec = importlib.util.spec_from_file_location("hosted_probe_under_test", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def probe(handler, **overrides):
    options = dict(endpoint="https://api.anthropic.com/v1/chat/completions",
                   provider="anthropic", model="claude-haiku-4-5-20251001",
                   api_key=SECRET, max_completion_tokens=4096)
    options.update(overrides)
    return asyncio.run(module().run_probe(
        ROOT, transport=httpx.MockTransport(handler), **options,
    ))


def test_probe_requires_explicit_opt_in_before_network():
    module()
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "--allow-hosted" in result.stderr


@pytest.mark.parametrize("override", [
    {"endpoint": "https://attacker.example/v1/chat/completions"},
    {"endpoint": "https://api.anthropic.com/v1/chat/completions?secret=hidden"},
    {"endpoint": "https://api.anthropic.com@attacker.example/v1/chat/completions"},
    {"api_key": " " + SECRET},
    {"api_key": ""},
    {"api_key": "sk-ant-oat01-private-token"},
    {"provider": "openai"},
    {"max_completion_tokens": 32769},
])
def test_probe_rejects_wrong_destination_or_credentials_before_network(override):
    calls = []

    def handler(request):
        calls.append(request)
        raise AssertionError("No request is permitted for invalid configuration")

    result = probe(handler, **override)
    assert result["status"] == "blocked"
    assert calls == []
    assert SECRET not in json.dumps(result)


def test_probe_distinguishes_native_and_compat_errors_without_retries_or_secret_echoes():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer " + SECRET
        payload = json.loads(request.content)
        if request.url.path == "/v1/messages":
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert payload["max_tokens"] == 16
            return httpx.Response(200, json={"content": [{"text": SECRET}],
                                            "usage": {"input_tokens": 8, "output_tokens": 1}})
        assert payload["max_completion_tokens"] == 16
        return httpx.Response(400, json={"error": {
            "type": "invalid_request_error", "code": SECRET, "param": SECRET,
            "message": "anthropic-version header is required; " + SECRET
            + " private-user@example.test https://example.test/secret",}})

    result = probe(handler)
    assert len(requests) == 2
    assert result["status"] == "failed"
    assert result["probes"]["native_minimal"]["http_status"] == 200
    error = result["probes"]["compatible_minimal"]
    assert error["http_status"] == 400
    assert "anthropic-version" in error["message_terms"]
    assert "required" in error["message_terms"]
    assert error["provider_error_param"] is None
    assert result["probes"]["project_extraction"]["status"] == "not_run"
    serialized = json.dumps(result)
    for forbidden in (SECRET, "private-user", "example.test", "Bearer", "content"):
        assert forbidden not in serialized


def test_probe_exercises_real_extractor_only_after_minimal_compat_success():
    requests = []

    def handler(request):
        requests.append(request)
        payload = json.loads(request.content)
        if request.url.path == "/v1/messages":
            return httpx.Response(200, json={"usage": {"input_tokens": 8, "output_tokens": 1}})
        if payload["max_completion_tokens"] == 16:
            return httpx.Response(200, json={"usage": {"prompt_tokens": 9,
                                                       "completion_tokens": 1}})
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["messages"][0]["role"] == "system"
        document = json.loads(payload["messages"][1]["content"])
        assert document["pages"][0]["text"]
        return httpx.Response(400, json={"error": {"type": "invalid_request_error",
            "param": "response_format", "message": "Unsupported parameter response_format"}})

    result = probe(handler)
    assert len(requests) == 3
    assert result["status"] == "failed"
    assert result["probes"]["project_extraction"]["http_status"] == 400
    assert result["probes"]["project_extraction"]["provider_error_param"] == "response_format"
    assert SECRET not in json.dumps(result)


def test_probe_success_records_usage_but_is_never_a_quality_evaluation():
    def handler(request):
        if request.url.path == "/v1/messages":
            return httpx.Response(200, json={"usage": {"input_tokens": 8, "output_tokens": 1}})
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    result = probe(handler)
    assert result["status"] == "completed"
    assert result["quality_evaluated"] is False
    assert result["probes"]["project_extraction"]["grounded_valid"] is False
    assert result["probes"]["project_extraction"]["prompt_tokens"] == 10


def test_probe_does_not_invent_status_200_for_an_extractor_response():
    def handler(request):
        payload = json.loads(request.content)
        if payload.get("max_completion_tokens") == 4096:
            return httpx.Response(204)
        return httpx.Response(200, json={})

    result = probe(handler)
    extraction = result["probes"]["project_extraction"]
    assert extraction.get("http_status") is None
    assert extraction["http_success"] is True
    assert extraction["grounded_valid"] is False
    assert result["quality_evaluated"] is False


@pytest.mark.parametrize("body", [
    [SECRET], {"error": SECRET}, {"error": {"type": [SECRET], "message": {"key": SECRET}}},
    {"error": {"type": SECRET, "message": "required " + SECRET + " field"}},
])
def test_probe_tolerates_malformed_error_envelopes_without_leaking_values(body):
    result = probe(lambda _: httpx.Response(400, json=body))
    assert result["status"] == "failed"
    assert SECRET not in json.dumps(result)


def test_probe_never_follows_a_redirect_with_the_key():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://attacker.example/"})

    result = probe(handler)
    assert result["status"] == "failed"
    assert len(requests) == 2
    assert all(r.url.host == "api.anthropic.com" for r in requests)


def test_probe_bounds_transport_failures_without_exposing_exception_text():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout(SECRET, request=request)

    result = probe(handler)
    assert result["status"] == "failed"
    assert len(requests) == 2
    assert SECRET not in json.dumps(result)
    assert result["probes"]["native_minimal"]["transport_error"] == "timeout"
