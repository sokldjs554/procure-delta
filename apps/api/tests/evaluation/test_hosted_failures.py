from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.evaluation.runner import extraction_eval, hosted_optimization
from app.extraction.hosted import HostedExtractor
from app.sources.http import ResilientHttpClient

CASE = {"id": "invalid", "text": "Unsupported prose.",
        "expected_valid": False, "expected_fields": {}}
SENTINEL = "private-value-must-never-appear"


@pytest.mark.parametrize(
    ("status", "body", "provider_type", "hint"),
    [
        (401, {"error": {"type": "authentication_error", "message": SENTINEL}},
         "authentication_error", None),
        (403, {"error": {"type": "permission_error", "message": SENTINEL}},
         "permission_error", None),
        (400, {"error": {"type": "invalid_request_error", "message":
                        "Your credit balance is too low. " + SENTINEL}},
         "invalid_request_error", "check_api_billing"),
        (400, {"error": {"type": "invalid_request_error", "message":
                        "anthropic-workspace-id header required. " + SENTINEL}},
         "invalid_request_error", "check_workspace_selection"),
        (400, {"error": {"type": SENTINEL, "code": SENTINEL, "message": SENTINEL}},
         None, None),
        (404, [SENTINEL], None, None),
        (400, {"error": {"type": [SENTINEL], "message": {"data": SENTINEL}}},
         None, None),
    ],
)
def test_http_failures_are_failed_measurements_with_only_safe_diagnostics(
    status, body, provider_type, hint,
):
    async def run():
        async with ResilientHttpClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)),
            max_attempts=1,
        ) as client:
            extractor = HostedExtractor(
                endpoint=f"https://example.test/{SENTINEL}?key={SENTINEL}",
                provider="test-provider", model="test-model", api_key=SENTINEL, client=client,
            )
            return await extraction_eval([CASE], extractor)

    result = asyncio.run(run())
    assert result["status"] == "failed"
    assert result["execution_errors"] == 1
    assert result["prompt_tokens"] is None
    assert result["completion_tokens"] is None
    assert result["hosted_calls"] == 1
    row = result["rows"][0]
    assert row["error_type"] == "HTTPStatusError"
    assert row["http_status"] == status
    assert row["provider_error_type"] == provider_type
    assert row["provider_hint"] == hint
    assert SENTINEL not in json.dumps(result)
    assert hosted_optimization(result, result)["status"] == "not_run"


def test_model_rejection_is_distinct_from_failed_http_execution():
    async def run():
        async with ResilientHttpClient(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 2}},
        ))) as client:
            return await extraction_eval([CASE], HostedExtractor(
                endpoint="https://example.test", provider="test", model="test", client=client,
            ))

    result = asyncio.run(run())
    assert result["status"] == "measured"
    assert result["execution_errors"] == 0
    assert result["prompt_tokens"] == 10
    assert result["rows"][0]["valid"] is False
    assert result["rows"][0]["http_status"] is None


def test_failed_cli_run_retains_diagnostic_artifact_but_cannot_replace_public_result(
    tmp_path, monkeypatch, capsys,
):
    from app.evaluation.hosted_artifact import HostedEvaluationError

    script = Path(__file__).resolve().parents[4] / "scripts/run_eval.py"
    spec = importlib.util.spec_from_file_location("run_eval_under_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    target = tmp_path / "apps/api/app/evaluation/results/local.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"existing_result": true}\n', encoding="utf-8")
    output = tmp_path / "diagnostic.json"
    row = {"id": "invalid", "error_type": "HTTPStatusError", "http_status": 401,
           "provider_error_type": "authentication_error", "provider_hint": None}
    route = {"status": "failed", "execution_errors": 1, "rows": [row]}

    async def failed_run(*args, **kwargs):
        return {"schema_version": 1, "provenance": {"synthetic": True},
                "extraction_routes": {"hosted_all": route, "hosted_gated": route}}

    monkeypatch.setattr(
        "app.config.get_settings", lambda: SimpleNamespace(extraction_mode="hosted")
    )
    monkeypatch.setattr("app.extraction.hosted.configured_extractor", lambda _: object())
    monkeypatch.setattr("app.evaluation.runner.run_evaluation", failed_run)
    monkeypatch.setattr(sys, "argv", [str(script), "--allow-hosted", "--publish",
                                      "--output", str(output)])
    with pytest.raises(HostedEvaluationError):
        module.main()
    assert json.loads(output.read_text())["extraction_routes"]["hosted_all"]["status"] == "failed"
    assert json.loads(target.read_text()) == {"existing_result": True}
    assert '"http_status": 401' in capsys.readouterr().out
