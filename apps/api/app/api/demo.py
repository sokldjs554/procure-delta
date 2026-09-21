from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.demo.control_room import build_scenario, list_scenarios

router = APIRouter(prefix="/api/v1/demo/pipeline", tags=["demo"])


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioSummaryDTO(DTO):
    id: str
    title: str
    description: str


class PipelineStageDTO(DTO):
    id: str
    label: str
    kind: Literal["system", "deterministic", "ocr", "llm", "notification"]
    status: Literal["passed", "warning", "blocked", "not_run"]
    input: dict[str, Any]
    output: dict[str, Any]
    evidence: list[dict[str, Any]]
    decision: dict[str, Any]
    measured_duration_ms: float | None
    notice: str | None


class PipelineScenarioDTO(DTO):
    scenario_id: str
    title: str
    description: str
    synthetic: Literal[True]
    source_scope: Literal["packaged_fixture", "committed_verification_artifact"]
    stages: list[PipelineStageDTO]


@router.get("/scenarios", response_model=list[ScenarioSummaryDTO])
def scenarios() -> list[ScenarioSummaryDTO]:
    return [ScenarioSummaryDTO.model_validate(asdict(row)) for row in list_scenarios()]


@router.get("/scenarios/{scenario_id}", response_model=PipelineScenarioDTO)
def scenario(scenario_id: str) -> PipelineScenarioDTO:
    try:
        value = build_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown pipeline scenario") from exc
    return PipelineScenarioDTO.model_validate(asdict(value))
