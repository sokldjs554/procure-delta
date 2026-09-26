from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
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
    rows = route.get("rows", [])
    if route.get("execution_errors") or (
        isinstance(rows, list)
        and any(isinstance(row, dict) and row.get("error_type") for row in rows)
    ):
        raise HostedEvaluationError(f"{name} contains execution errors")
    return route


def _positive_latency(route: dict[str, Any], key: str, name: str) -> float:
    latency = route.get("latency_ms")
    if not isinstance(latency, dict):
        raise HostedEvaluationError(f"{name} latency is missing")
    value = latency.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise HostedEvaluationError(f"{name} {key} latency is not measured")
    return float(value)


def _nonnegative_int(value: Any, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HostedEvaluationError(message)
    return int(value)


def _checked_rate(value: Any, expected: float | None, label: str) -> float | None:
    if expected is None:
        if value is not None:
            raise HostedEvaluationError(f"{label} is unavailable from measured route totals")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HostedEvaluationError(f"{label} is not measured")
    result = float(value)
    if not math.isfinite(result) or not math.isclose(
        result, expected, rel_tol=1e-12, abs_tol=1e-12,
    ):
        raise HostedEvaluationError(f"{label} does not match measured route totals")
    # Return the recomputed value. Genuine increases are negative reductions and
    # must remain publishable; requiring a positive result would bias evidence.
    return expected


def _reported_cost(route: dict[str, Any], name: str) -> Decimal | None:
    value = route.get("reported_cost_per_document")
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise HostedEvaluationError(f"{name} reported cost is invalid") from error
    if not result.is_finite() or result < 0:
        raise HostedEvaluationError(f"{name} reported cost is invalid")
    return result


def _token_total(route: dict[str, Any], name: str) -> int:
    prompt = _nonnegative_int(
        route.get("prompt_tokens"), f"{name} prompt tokens are not measured"
    )
    completion = _nonnegative_int(
        route.get("completion_tokens"), f"{name} completion tokens are not measured"
    )
    return prompt + completion


def _validate_rows(route: dict[str, Any], name: str) -> dict[str, tuple[bool, int]] | None:
    """Reconcile case-bearing artifacts; retain legacy aggregate-only compatibility."""
    if "rows" not in route:
        return None
    rows = route["rows"]
    if not isinstance(rows, list) or not rows:
        raise HostedEvaluationError(f"{name} rows are missing")
    cases = {}
    counts = dict.fromkeys(("correct_fields", "expected_fields", "schema_failures",
                           "grounded_accepted_documents", "hosted_calls",
                           "prompt_tokens", "completion_tokens"), 0)
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise HostedEvaluationError(f"{name} rows have invalid case identifiers")
        if row["id"] in cases or any(type(row.get(key)) is not bool for key in (
            "expected_valid", "valid", "schema_valid",
        )):
            raise HostedEvaluationError(f"{name} rows have duplicate cases or invalid statuses")
        fields = row.get("fields")
        if not isinstance(fields, dict):
            raise HostedEvaluationError(f"{name} rows have no field counts")
        correct = _nonnegative_int(fields.get("correct"), f"{name} rows have invalid correct count")
        support = _nonnegative_int(fields.get("expected_fields"),
                                   f"{name} rows have invalid field support")
        if correct > support:
            raise HostedEvaluationError(f"{name} rows have correct count above support")
        cases[row["id"]] = (row["expected_valid"], support)
        if row["expected_valid"]:
            counts["correct_fields"] += correct
            counts["expected_fields"] += support
        counts["schema_failures"] += int(not row["schema_valid"])
        counts["grounded_accepted_documents"] += int(row["valid"])
        if (row.get("response_diagnostics") is not None
                or any(row.get(key) is not None for key in ("prompt_tokens", "completion_tokens"))):
            counts["hosted_calls"] += 1
            for key in ("prompt_tokens", "completion_tokens"):
                counts[key] += _nonnegative_int(row.get(key), f"{name} rows have missing {key}")
    counts["documents"] = len(rows)
    for key, expected in counts.items():
        actual = _nonnegative_int(route.get(key), f"{name} {key} is missing from rows aggregate")
        if actual != expected:
            raise HostedEvaluationError(f"{name} {key} does not match rows")
    _checked_rate(route.get("field_accuracy"),
                  counts["correct_fields"] / counts["expected_fields"]
                  if counts["expected_fields"] else None, f"{name} field accuracy from rows")
    _checked_rate(route.get("grounded_acceptance_rate"),
                  counts["grounded_accepted_documents"] / len(rows),
                  f"{name} grounded acceptance from rows")
    return cases


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
    all_cases = _validate_rows(all_route, "hosted_all")
    gated_cases = _validate_rows(gated_route, "hosted_gated")
    if all_cases != gated_cases:
        raise HostedEvaluationError("hosted routes did not evaluate the same cases")

    optimization = raw.get("hosted_optimization")
    if not isinstance(optimization, dict) or optimization.get("status") != "measured":
        raise HostedEvaluationError("hosted optimization was not measured")
    if optimization.get("all_calls") != all_calls or optimization.get("gated_calls") != gated_calls:
        raise HostedEvaluationError("hosted optimization call counts do not match routes")

    avoided = _nonnegative_int(optimization.get("avoided_calls"), "avoided calls is invalid")
    if avoided != all_calls - gated_calls:
        raise HostedEvaluationError("avoided calls does not match measured route totals")
    call_reduction = _checked_rate(
        optimization.get("call_reduction_rate"), (all_calls - gated_calls) / all_calls,
        "call reduction",
    )
    token_reduction = _checked_rate(
        optimization.get("token_reduction_rate"), (all_tokens - gated_tokens) / all_tokens,
        "token reduction",
    )
    all_cost, gated_cost = _reported_cost(all_route, "hosted_all"), _reported_cost(
        gated_route, "hosted_gated",
    )
    cost_reduction = _checked_rate(
        optimization.get("reported_cost_reduction_rate"),
        float((all_cost - gated_cost) / all_cost)
        if all_cost is not None and all_cost > 0 and gated_cost is not None else None,
        "cost reduction",
    )

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
        "call_reduction_rate": call_reduction,
        "token_reduction_rate": token_reduction,
        "reported_cost_reduction_rate": cost_reduction,
        "cost_basis": optimization.get("cost_basis"),
    }
