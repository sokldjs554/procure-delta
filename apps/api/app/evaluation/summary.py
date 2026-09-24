"""Small allowlisted public projection of a committed, offline evaluation artifact."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from app.evaluation.hosted_artifact import validate_hosted_artifact


class EvaluationRouteSummary(BaseModel):
    status: Literal['measured', 'not_run'] = 'not_run'
    support: int = 0
    field_accuracy: float | None = None
    schema_failures: int | None = None
    grounded_acceptance_rate: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    hosted_calls: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reported_cost: float | None = None
    language: str | None = None
    notice: str | None = None


class HostedOptimizationSummary(BaseModel):
    status: Literal['measured', 'not_run'] = 'not_run'
    all_calls: int | None = None
    gated_calls: int | None = None
    avoided_calls: int | None = None
    call_reduction_rate: float | None = None
    all_tokens: int | None = None
    gated_tokens: int | None = None
    token_reduction_rate: float | None = None
    reported_cost_reduction_rate: float | None = None
    cost_basis: str | None = None
    notice: str | None = None


class EvaluationSummary(BaseModel):
    status: Literal['measured', 'not_run'] = 'not_run'
    synthetic: bool = True
    public_real_records: int = 0
    measured_at: str | None = None
    dataset_version: str | None = None
    dataset_sha256: str | None = None
    source_sha256: str | None = None
    extraction_accuracy: float | None = None
    extraction_correct: int = 0
    extraction_support: int = 0
    delta_precision: float | None = None
    delta_recall: float | None = None
    delta_support: int = 0
    lifecycle_precision: float | None = None
    lifecycle_resolved: int = 0
    lifecycle_cases: int = 0
    replay_queries: int = 0
    ocr_accuracy: float | None = None
    ocr_correct: int = 0
    ocr_support: int = 0
    ocr_language: str | None = None
    hosted_evaluated: bool = False
    hosted_optimization: HostedOptimizationSummary = HostedOptimizationSummary()
    routes: dict[str, EvaluationRouteSummary] = {}
    notice: str = ('저장된 소규모 합성 회귀 평가입니다. 현재 운영 지표나 '
                   '실제 조달 데이터·한국어 스캔·LLM 품질 성적이 아닙니다.')


def _latency(metrics: dict[str, Any], key: str) -> float | None:
    latency = metrics.get('latency_ms')
    if not isinstance(latency, dict):
        return None
    value = latency.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _hosted_route(value: dict[str, Any]) -> EvaluationRouteSummary:
    status = value.get('status')
    if status != 'measured':
        return EvaluationRouteSummary(
            status='not_run',
            notice=str(value.get('reason')) if value.get('reason') else None,
        )
    metrics = value.get('metrics')
    if not isinstance(metrics, dict):
        # Measured evaluation artifacts store route metrics directly; older wrappers may nest them.
        metrics = value
    return EvaluationRouteSummary(
        status='measured',
        support=int(metrics.get('expected_fields', metrics.get('support', 0)) or 0),
        field_accuracy=metrics.get('field_accuracy'),
        schema_failures=metrics.get('schema_failures'),
        grounded_acceptance_rate=metrics.get('grounded_acceptance_rate'),
        p50_latency_ms=_latency(metrics, 'p50'),
        p95_latency_ms=_latency(metrics, 'p95'),
        hosted_calls=metrics.get('hosted_calls'),
        prompt_tokens=metrics.get('prompt_tokens'),
        completion_tokens=metrics.get('completion_tokens'),
        reported_cost=metrics.get('reported_cost_per_document'),
    )


def read_korean_ocr_route(path: Path) -> EvaluationRouteSummary:
    if not path.exists():
        return EvaluationRouteSummary(
            status="not_run",
            notice="stored Korean OCR artifact is unavailable",
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or raw.get("synthetic") is not True:
        raise ValueError("invalid Korean OCR artifact")
    measurement = raw.get("measurement")
    if not isinstance(measurement, dict) or measurement.get("status") != "measured":
        return EvaluationRouteSummary(
            status="not_run",
            notice="Korean OCR artifact was not measured",
        )
    return EvaluationRouteSummary(
        status="measured",
        support=int(measurement.get("expected_fields", 0) or 0),
        field_accuracy=measurement.get("field_accuracy"),
        hosted_calls=int(measurement.get("actual_recognition_invocations", 0) or 0),
        language=measurement.get("language"),
        notice=str(raw.get("limitation") or measurement.get("limitation") or ""),
    )


def read_summary(path: Path) -> EvaluationSummary:
    if not path.exists():
        return EvaluationSummary()
    raw = json.loads(path.read_text(encoding='utf-8'))
    if raw.get('schema_version') != '1' and raw.get('schema_version') != 1:
        raise ValueError('unknown evaluation artifact schema')
    source = raw['provenance']
    if source.get('synthetic') is not True:
        raise ValueError('this public regression panel only accepts labeled synthetic artifacts')
    extraction = raw['extraction_routes']['deterministic']
    delta, lifecycle, ocr = raw['delta'], raw['lifecycle'], raw['ocr']
    routes = {
        'deterministic': EvaluationRouteSummary(
            status='measured',
            support=extraction['expected_fields'],
            field_accuracy=extraction['field_accuracy'],
            schema_failures=extraction.get('schema_failures'),
            grounded_acceptance_rate=extraction.get('grounded_acceptance_rate'),
            p50_latency_ms=_latency(extraction, 'p50'),
            p95_latency_ms=_latency(extraction, 'p95'),
            hosted_calls=extraction.get('hosted_calls'),
            prompt_tokens=extraction.get('prompt_tokens'),
            completion_tokens=extraction.get('completion_tokens'),
            reported_cost=extraction.get('reported_cost_per_document'),
            notice='로컬 deterministic extractor · 합성 회귀셋',
        ),
        'hosted_all': _hosted_route(raw['extraction_routes']['hosted_all']),
        'hosted_gated': _hosted_route(raw['extraction_routes']['hosted_gated']),
        'ocr': EvaluationRouteSummary(
            status='measured' if ocr.get('status') == 'measured' else 'not_run',
            support=int(ocr.get('expected_fields', 0) or 0),
            field_accuracy=ocr.get('field_accuracy'),
            hosted_calls=int(ocr.get('actual_recognition_invocations', 0) or 0),
            language=ocr.get('language'),
            notice=ocr.get('limitation'),
        ),
    }
    optimization_raw = raw.get('hosted_optimization', {})
    if not isinstance(optimization_raw, dict):
        optimization_raw = {}
    optimization = HostedOptimizationSummary(
        status='measured' if optimization_raw.get('status') == 'measured' else 'not_run',
        all_calls=optimization_raw.get('all_calls'),
        gated_calls=optimization_raw.get('gated_calls'),
        avoided_calls=optimization_raw.get('avoided_calls'),
        call_reduction_rate=optimization_raw.get('call_reduction_rate'),
        all_tokens=optimization_raw.get('all_tokens'),
        gated_tokens=optimization_raw.get('gated_tokens'),
        token_reduction_rate=optimization_raw.get('token_reduction_rate'),
        reported_cost_reduction_rate=optimization_raw.get('reported_cost_reduction_rate'),
        cost_basis=optimization_raw.get('cost_basis'),
        notice=(
            str(optimization_raw.get('reason'))
            if optimization_raw.get('reason')
            else None
        ),
    )
    return EvaluationSummary(
        status='measured', measured_at=raw['created_at'], dataset_version=raw['dataset_version'],
        public_real_records=raw['public_real_records'],
        dataset_sha256=source['dataset_sha256'], source_sha256=source['source_sha256'],
        extraction_accuracy=extraction['field_accuracy'],
        extraction_correct=extraction['correct_fields'],
        extraction_support=extraction['expected_fields'],
        delta_precision=delta['fields']['precision'], delta_recall=delta['fields']['recall'],
        delta_support=delta['fields']['expected_support'],
        lifecycle_precision=lifecycle['links']['precision'],
        lifecycle_resolved=lifecycle['links']['predicted_support'],
        lifecycle_cases=lifecycle['cases'],
        replay_queries=len(raw['historical_replay']),
        ocr_accuracy=ocr.get('field_accuracy'), ocr_correct=ocr.get('correct_fields', 0),
        ocr_support=ocr.get('expected_fields', 0), ocr_language=ocr.get('language'),
        hosted_evaluated=raw['extraction_routes']['hosted_all'].get('status') == 'measured',
        hosted_optimization=optimization,
        routes=routes,
    )


def read_published_summary(directory: Path) -> EvaluationSummary:
    """Combine independently measured artifacts without rewriting their provenance."""
    result = read_summary(directory / "local.json")
    result.routes["ocr_korean"] = read_korean_ocr_route(directory / "korean-ocr.json")
    hosted_path = directory / "hosted.json"
    if not hosted_path.exists():
        return result
    raw = json.loads(hosted_path.read_text(encoding="utf-8"))
    validate_hosted_artifact(raw)
    hosted = read_summary(hosted_path)
    if hosted.dataset_sha256 != result.dataset_sha256:
        raise ValueError("published hosted and local datasets do not match")
    for name in ("hosted_all", "hosted_gated"):
        route = raw["extraction_routes"][name]
        model = route["extractor"]["model"]
        commit = raw["provenance"]["git_commit"]
        result.routes[name] = hosted.routes[name]
        result.routes[name].notice = (
            f"{model} · {hosted.measured_at} · commit {commit}. "
            f"저자 작성 합성 {route['documents']}건의 1회 실측이며 "
            "실제 문서 일반화 성능이 아닙니다."
        )
        normal_rejections = sum(row["expected_valid"] and not row["valid"] for row in route["rows"])
        result.routes[name].notice = (
            (result.routes[name].notice or "")
            + f" 정상 문서 중 검증 거절은 {normal_rejections}건입니다."
        )
    gated_rows = raw["extraction_routes"]["hosted_gated"]["rows"]
    local_rows = [row for row in gated_rows if row["response_diagnostics"] is None]
    local_correct = sum(row["fields"]["correct"] for row in local_rows)
    local_support = sum(row["fields"]["expected_fields"] for row in local_rows)
    recovered = sum(
        row["expected_valid"] and row["valid"] and row["response_diagnostics"] is not None
        for row in gated_rows
    )
    result.routes["hosted_gated"].notice = (result.routes["hosted_gated"].notice or "") + (
        f" 로컬 규칙 처리 {len(local_rows)}건의 정답 필드는 {local_correct}/{local_support}이며, "
        f"외부 모델이 추가로 수용한 정상 문서는 {recovered}건입니다."
    )
    result.hosted_evaluated = True
    result.hosted_optimization = hosted.hosted_optimization
    result.hosted_optimization.notice = (
        "경로 전체 지연시간에는 gated의 로컬 처리도 포함됩니다. "
        "호출 수는 논리 호출이며 HTTP 재시도 횟수와 다릅니다. "
        "반환되지 않은 비용은 미측정으로 유지합니다."
    )
    result.notice = (
        "서로 다른 시점에 저장한 소규모 합성 회귀 결과입니다. "
        "아래 저장 시각과 소스 해시는 로컬·영어 OCR 실행 기준이며, "
        "외부 Claude의 별도 실행 시각과 commit은 경로 설명에 표시합니다. "
        "현재 운영 지표나 실제 조달 문서의 일반화 성능이 아닙니다."
    )
    return result
