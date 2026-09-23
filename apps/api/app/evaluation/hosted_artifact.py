from __future__ import annotations

from typing import Any


FORBIDDEN_KEY_PARTS = ("api_key", "authorization", "secret", "access_token", "bearer")


class HostedEvaluationError(ValueError):
    pass


def _forbidden_key(value: object) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                return str(key)
            nested = _forbidden_key(item)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _forbidden_key(item)
            if nested:
                return nested
    return None


def _route(raw: dict[str, Any], name: str) -> dict[str, Any]:
    routes = raw.get("extraction_routes")
    if not isinstance(routes, dict):
        raise HostedEvaluationError("extraction_routes is missing")
    route = routes.get(name)
    if not isinstance(route, dict) or route.get("status") != "measured":
        raise HostedEvaluationError(f"{name} was not measured")
    return route


def _positive_latency(route: dict[str, Any], key: str, name: str) -> float:
    latency = route.get("latency_ms")
    if not isinstance(latency, dict):
        raise HostedEvaluationError(f"{name} latency is missing")
    value = latency.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise HostedEvaluationError(f"{name} {key} latency is not measured")
    return float(value)


def _token_total(route: dict[str, Any], name: str) -> int:
    prompt = route.get("prompt_tokens")
    completion = route.get("completion_tokens")
    for label, value in (("prompt", prompt), ("completion", completion)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise HostedEvaluationError(f"{name} {label} tokens are not measured")
    return prompt + completion


def validate_hosted_artifact(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schema_version") not in {1, "1"}:
        raise HostedEvaluationError("unknown evaluation artifact schema")
    provenance = raw.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("synthetic") is not True:
        raise HostedEvaluationError("hosted evaluation must use the frozen synthetic dataset")

    forbidden = _forbidden_key(raw)
    if forbidden:
        raise HostedEvaluationError(f"artifact contains forbidden secret-like key: {forbidden}")

    all_route = _route(raw, "hosted_all")
    gated_route = _route(raw, "hosted_gated")

    all_calls = all_route.get("hosted_calls")
    gated_calls = gated_route.get("hosted_calls")
    if isinstance(all_calls, bool) or not isinstance(all_calls, int) or all_calls <= 0:
        raise HostedEvaluationError("hosted_all call count is not measured")
    if (
        isinstance(gated_calls, bool)
        or not isinstance(gated_calls, int)
        or gated_calls < 0
        or gated_calls > all_calls
    ):
        raise HostedEvaluationError("hosted_gated call count is invalid")

    all_tokens = _token_total(all_route, "hosted_all")
    gated_tokens = _token_total(gated_route, "hosted_gated")
    if all_tokens <= 0:
        raise HostedEvaluationError("hosted_all token usage is empty")

    for name, route in (("hosted_all", all_route), ("hosted_gated", gated_route)):
        _positive_latency(route, "p50", name)
        _positive_latency(route, "p95", name)

    optimization = raw.get("hosted_optimization")
    if not isinstance(optimization, dict) or optimization.get("status") != "measured":
        raise HostedEvaluationError("hosted optimization was not measured")
    if optimization.get("all_calls") != all_calls or optimization.get("gated_calls") != gated_calls:
        raise HostedEvaluationError("hosted optimization call counts do not match routes")

    call_reduction = optimization.get("call_reduction_rate")
    token_reduction = optimization.get("token_reduction_rate")
    for label, value in (
        ("call reduction", call_reduction),
        ("token reduction", token_reduction),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HostedEvaluationError(f"{label} is not measured")
        if not 0 <= value <= 1:
            raise HostedEvaluationError(f"{label} is outside [0, 1]")

    if optimization.get("all_tokens") != all_tokens:
        raise HostedEvaluationError("optimization all_tokens does not match hosted_all")
    if optimization.get("gated_tokens") != gated_tokens:
        raise HostedEvaluationError("optimization gated_tokens does not match hosted_gated")

    return {
        "hosted_all_calls": all_calls,
        "hosted_gated_calls": gated_calls,
        "avoided_calls": all_calls - gated_calls,
        "all_tokens": all_tokens,
        "gated_tokens": gated_tokens,
        "call_reduction_rate": float(call_reduction),
        "token_reduction_rate": float(token_reduction),
        "reported_cost_reduction_rate": optimization.get("reported_cost_reduction_rate"),
        "cost_basis": optimization.get("cost_basis"),
    }
