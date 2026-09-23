from __future__ import annotations

from copy import deepcopy

import pytest

from app.evaluation.hosted_artifact import HostedEvaluationError, validate_hosted_artifact


def artifact() -> dict:
    return {
        "schema_version": 1,
        "provenance": {"synthetic": True},
        "extraction_routes": {
            "hosted_all": {
                "status": "measured",
                "hosted_calls": 10,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "latency_ms": {"p50": 120.0, "p95": 240.0},
            },
            "hosted_gated": {
                "status": "measured",
                "hosted_calls": 4,
                "prompt_tokens": 40,
                "completion_tokens": 20,
                "latency_ms": {"p50": 90.0, "p95": 180.0},
            },
        },
        "hosted_optimization": {
            "status": "measured",
            "all_calls": 10,
            "gated_calls": 4,
            "avoided_calls": 6,
            "call_reduction_rate": 0.6,
            "all_tokens": 150,
            "gated_tokens": 60,
            "token_reduction_rate": 0.6,
            "reported_cost_reduction_rate": None,
            "cost_basis": None,
        },
    }


def test_hosted_validator_requires_measured_usage_latency_and_optimization() -> None:
    summary = validate_hosted_artifact(artifact())
    assert summary["avoided_calls"] == 6
    assert summary["all_tokens"] == 150
    assert summary["gated_tokens"] == 60
    assert summary["call_reduction_rate"] == pytest.approx(0.6)
    assert summary["token_reduction_rate"] == pytest.approx(0.6)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("extraction_routes", "hosted_all", "status"), "not_run", "hosted_all was not measured"),
        (("extraction_routes", "hosted_all", "prompt_tokens"), None, "prompt tokens"),
        (("extraction_routes", "hosted_gated", "latency_ms", "p95"), None, "p95 latency"),
        (("hosted_optimization", "token_reduction_rate"), None, "token reduction"),
    ],
)
def test_hosted_validator_rejects_incomplete_measurement(path, value, message) -> None:
    raw = deepcopy(artifact())
    cursor = raw
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(HostedEvaluationError, match=message):
        validate_hosted_artifact(raw)


def test_hosted_validator_rejects_secret_like_artifact_keys() -> None:
    raw = artifact()
    raw["debug"] = {"api_key": "must-not-be-here"}
    with pytest.raises(HostedEvaluationError, match="forbidden secret-like key"):
        validate_hosted_artifact(raw)


def test_hosted_validator_allows_optional_provider_cost_to_remain_null() -> None:
    summary = validate_hosted_artifact(artifact())
    assert summary["reported_cost_reduction_rate"] is None
    assert summary["cost_basis"] is None


def test_hosted_validator_rejects_execution_errors_despite_measured_status_and_usage() -> None:
    raw = artifact()
    raw["extraction_routes"]["hosted_gated"]["rows"] = [
        {"error_type": "HTTPStatusError", "http_status": 401},
    ]
    with pytest.raises(HostedEvaluationError, match="execution errors"):
        validate_hosted_artifact(raw)
