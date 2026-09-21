from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])


def resolve_artifact_root(module_path: Path) -> Path:
    resolved = module_path.resolve()
    for parent in resolved.parents:
        candidate = parent / "artifacts"
        if candidate.is_dir():
            return candidate
    for parent in resolved.parents:
        if parent.name == "app":
            return parent.parent / "artifacts"
    return resolved.parent / "artifacts"


ARTIFACT_ROOT = resolve_artifact_root(Path(__file__))
PUBLIC_SNAPSHOT = Path(__file__).resolve().parents[1] / "evaluation" / "results" / "engineering.json"


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CpuEvidence(DTO):
    status: Literal["measured", "not_run"]
    scope: str | None = None
    synthetic: bool | None = None
    normalized_records: int | None = None
    ranked_records: int | None = None
    delta_pairs: int | None = None
    elapsed_seconds: float | None = None
    records_per_second: float | None = None
    limitation: str | None = None


class FailureCase(DTO):
    name: str
    attempts: int
    succeeded: bool
    passed: bool


class FailureEvidence(DTO):
    status: Literal["measured", "not_run"]
    scope: str | None = None
    cases: list[FailureCase] = Field(default_factory=list)
    limitation: str | None = None


class GateEvidence(DTO):
    gate: str
    passed: bool
    elapsed_seconds: float | None = None


class ReleaseEvidence(DTO):
    status: Literal["measured", "not_run"]
    passed: bool | None = None
    readiness: str | None = None
    gates: list[GateEvidence] = Field(default_factory=list)
    dependencies: dict[str, bool] = Field(default_factory=dict)


class OptionalEvidence(DTO):
    status: Literal["measured", "not_run"]
    scope: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class EngineeringEvidence(DTO):
    cpu: CpuEvidence
    failure_drill: FailureEvidence
    release: ReleaseEvidence
    queue: OptionalEvidence
    http: OptionalEvidence
    query_plans: OptionalEvidence


def _read(relative: str) -> dict[str, Any] | None:
    path = ARTIFACT_ROOT / relative
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _cpu() -> CpuEvidence:
    value = _read("performance/cpu.json")
    if value is None:
        return CpuEvidence(status="not_run")
    return CpuEvidence(
        status="measured",
        scope=str(value.get("scope")) if value.get("scope") is not None else None,
        synthetic=value.get("synthetic") if isinstance(value.get("synthetic"), bool) else None,
        normalized_records=(
            value.get("normalized_records")
            if isinstance(value.get("normalized_records"), int)
            else None
        ),
        ranked_records=(
            value.get("ranked_records") if isinstance(value.get("ranked_records"), int) else None
        ),
        delta_pairs=value.get("delta_pairs") if isinstance(value.get("delta_pairs"), int) else None,
        elapsed_seconds=(
            float(value["elapsed_seconds"])
            if isinstance(value.get("elapsed_seconds"), (int, float))
            else None
        ),
        records_per_second=(
            float(value["cpu_pipeline_records_per_second"])
            if isinstance(value.get("cpu_pipeline_records_per_second"), (int, float))
            else None
        ),
        limitation=str(value.get("limitation")) if value.get("limitation") else None,
    )


def _failures() -> FailureEvidence:
    value = _read("failures/http.json")
    if value is None:
        return FailureEvidence(status="not_run")
    cases: list[FailureCase] = []
    for item in value.get("cases", []):
        if not isinstance(item, dict):
            continue
        name, attempts, succeeded, passed = (
            item.get("name"),
            item.get("attempts"),
            item.get("succeeded"),
            item.get("passed"),
        )
        if (
            isinstance(name, str)
            and isinstance(attempts, int)
            and isinstance(succeeded, bool)
            and isinstance(passed, bool)
        ):
            cases.append(
                FailureCase(
                    name=name,
                    attempts=attempts,
                    succeeded=succeeded,
                    passed=passed,
                )
            )
    return FailureEvidence(
        status="measured",
        scope=str(value.get("scope")) if value.get("scope") else None,
        cases=cases,
        limitation=str(value.get("limitation")) if value.get("limitation") else None,
    )


def _release() -> ReleaseEvidence:
    value = _read("verification/release-gate.json")
    if value is None:
        return ReleaseEvidence(status="not_run")
    gates: list[GateEvidence] = []
    for item in value.get("gates", []):
        if not isinstance(item, dict) or not isinstance(item.get("gate"), str):
            continue
        if not isinstance(item.get("passed"), bool):
            continue
        elapsed = item.get("elapsed_seconds")
        gates.append(
            GateEvidence(
                gate=item["gate"],
                passed=item["passed"],
                elapsed_seconds=float(elapsed) if isinstance(elapsed, (int, float)) else None,
            )
        )
    readiness = value.get("readiness_snapshot")
    readiness_dict = readiness if isinstance(readiness, dict) else {}
    dependencies = readiness_dict.get("dependencies")
    safe_dependencies = (
        {
            str(key): flag
            for key, flag in dependencies.items()
            if isinstance(key, str) and isinstance(flag, bool)
        }
        if isinstance(dependencies, dict)
        else {}
    )
    return ReleaseEvidence(
        status="measured",
        passed=value.get("passed") if isinstance(value.get("passed"), bool) else None,
        readiness=(
            str(readiness_dict.get("status")) if readiness_dict.get("status") is not None else None
        ),
        gates=gates,
        dependencies=safe_dependencies,
    )


_OPTIONAL_KEYS = {
    "scope",
    "synthetic",
    "records",
    "requested_records",
    "completed_records",
    "elapsed_seconds",
    "records_per_second",
    "requests",
    "successful_requests",
    "failed_requests",
    "p50_ms",
    "p95_ms",
    "before",
    "after",
    "improvement_ratio",
    "successful",
    "limitation",
    "endpoints",
    "client_observed_only",
    "candidate_adopted",
    "candidate_rolled_back",
    "caution",
}


def _optional(relative: str) -> OptionalEvidence:
    value = _read(relative)
    if value is None:
        return OptionalEvidence(status="not_run")
    metrics = {
        key: value[key]
        for key in _OPTIONAL_KEYS
        if key in value and isinstance(value[key], (str, int, float, bool, type(None), dict, list))
    }
    return OptionalEvidence(
        status="measured",
        scope=str(value.get("scope")) if value.get("scope") else None,
        metrics=metrics,
    )


def _packaged_snapshot() -> EngineeringEvidence | None:
    if not PUBLIC_SNAPSHOT.is_file():
        return None
    try:
        value = json.loads(PUBLIC_SNAPSHOT.read_text(encoding="utf-8"))
        return EngineeringEvidence.model_validate(value)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


@router.get("/engineering-evidence", response_model=EngineeringEvidence)
def engineering_evidence() -> EngineeringEvidence:
    snapshot = _packaged_snapshot()
    cpu = _cpu()
    failure_drill = _failures()
    release = _release()
    queue = _optional("performance/queue.json")
    http = _optional("performance/http.json")
    query_plans = _optional("performance/query-plans.json")
    if snapshot is not None:
        if cpu.status == "not_run":
            cpu = snapshot.cpu
        if failure_drill.status == "not_run":
            failure_drill = snapshot.failure_drill
        if release.status == "not_run":
            release = snapshot.release
        if queue.status == "not_run":
            queue = snapshot.queue
        if http.status == "not_run":
            http = snapshot.http
        if query_plans.status == "not_run":
            query_plans = snapshot.query_plans
    return EngineeringEvidence(
        cpu=cpu,
        failure_drill=failure_drill,
        release=release,
        queue=queue,
        http=http,
        query_plans=query_plans,
    )
