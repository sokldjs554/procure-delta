from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.delta.engine import DeltaSnapshot, compute_delta
from app.demo.dataset import demo_records, document_html
from app.documents.download import StoredAttachment
from app.documents.parsers import parse_document
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.schemas import DocumentBundle, DocumentPage
from app.extraction.validation import validate_extraction
from app.models import OpportunityVersion, RawRecord
from app.ranking.eligibility import (
    EligibilityOpportunity,
    EligibilityProfile,
    EligibilityDecision,
    EvidenceClaim,
    evaluate_eligibility,
)
from app.ranking.features import RankingOpportunity, RankingProfile
from app.ranking.ranker import RankingDecision, RankingEligibility, rank_opportunity
from app.services.normalize import NormalizedOpportunityInput, normalize_raw_record
from app.sources.base import RawSourceRecord

StageKind = Literal["system", "deterministic", "ocr", "llm", "notification"]
StageStatus = Literal["passed", "warning", "blocked", "not_run"]

_STAGE_DEFINITIONS: tuple[tuple[str, str, StageKind], ...] = (
    ("collect", "수집", "system"),
    ("dedupe", "중복 제거", "system"),
    ("normalize", "정규화", "deterministic"),
    ("documents", "문서 파싱", "system"),
    ("ocr-route", "OCR 라우팅", "ocr"),
    ("extract", "구조화 추출", "deterministic"),
    ("validate", "스키마·근거 검증", "deterministic"),
    ("lifecycle", "생애주기 연결", "deterministic"),
    ("delta", "Delta", "deterministic"),
    ("eligibility", "참여 조건", "deterministic"),
    ("ranking", "관련도 순위", "deterministic"),
    ("notification", "알림 판단", "notification"),
)

_FAILURE_CASES: tuple[dict[str, Any], ...] = (
    {
        "name": "timeout-recovery",
        "attempts": 3,
        "backoff_seconds": [0.25, 0.5],
        "succeeded": True,
    },
    {
        "name": "rate-limit-recovery",
        "attempts": 2,
        "backoff_seconds": [0.25],
        "succeeded": True,
    },
    {
        "name": "server-error-terminal",
        "attempts": 3,
        "backoff_seconds": [0.25, 0.5],
        "succeeded": False,
    },
    {
        "name": "forbidden-not-retried",
        "attempts": 1,
        "backoff_seconds": [],
        "succeeded": False,
    },
)


@dataclass(frozen=True)
class ScenarioSummary:
    id: str
    title: str
    description: str


@dataclass(frozen=True)
class PipelineStage:
    id: str
    label: str
    kind: StageKind
    status: StageStatus
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[dict[str, Any], ...] = ()
    decision: dict[str, Any] = field(default_factory=dict)
    measured_duration_ms: float | None = None
    notice: str | None = None


@dataclass(frozen=True)
class PipelineScenario:
    scenario_id: str
    title: str
    description: str
    synthetic: bool
    source_scope: str
    stages: tuple[PipelineStage, ...]


CATALOG = (
    ScenarioSummary("new-opportunity", "신규 공고", "수집부터 추천·알림 판단까지"),
    ScenarioSummary(
        "amendment-eligibility-change",
        "정정으로 조건 변경",
        "버전 변경이 Delta와 참여 가능 여부에 미치는 영향",
    ),
    ScenarioSummary(
        "failure-recovery",
        "장애와 복구",
        "재시도·비재시도·종료 실패 경계를 확인",
    ),
)


def list_scenarios() -> tuple[ScenarioSummary, ...]:
    return CATALOG


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _raw_record(
    source: RawSourceRecord,
    *,
    source_id: UUID,
    raw_id: UUID,
) -> RawRecord:
    payload = dict(source.raw_payload)
    return RawRecord(
        id=raw_id,
        source_id=source_id,
        source_record_id=source.source_record_id,
        fetched_at=source.source_updated_at or datetime(2026, 9, 16, tzinfo=UTC),
        source_updated_at=source.source_updated_at,
        payload_json=payload,
        payload_sha256=_payload_hash(payload),
        schema_version="1",
        normalization_status="normalized",
    )


def _version(
    normalized: NormalizedOpportunityInput,
    *,
    opportunity_id: UUID,
    version_id: UUID,
    raw_id: UUID,
    version_number: int,
) -> OpportunityVersion:
    return OpportunityVersion(
        id=version_id,
        opportunity_id=opportunity_id,
        raw_record_id=raw_id,
        version_number=version_number,
        source_record_id=normalized.source_record_id,
        effective_at=normalized.effective_at,
        normalized_json=normalized.normalized_json,
        normalized_sha256=normalized.normalized_sha256,
        extraction_version="control-room-v1",
        transition_kind="current",
        transition_at=normalized.effective_at,
    )


def _claim(raw: RawRecord, normalized: NormalizedOpportunityInput, field_name: str) -> EvidenceClaim | None:
    value = normalized.normalized_json.get(field_name)
    if value in (None, "", []):
        return None
    return EvidenceClaim(
        field=field_name,
        value=value,
        evidence=(
            {
                "kind": "raw",
                "source_record_id": raw.source_record_id,
                "payload_sha256": raw.payload_sha256,
                "json_pointer": f"/{field_name}",
            },
        ),
    )


def _eligibility(
    profile: EligibilityProfile,
    raw: RawRecord,
    normalized: NormalizedOpportunityInput,
) -> EligibilityDecision:
    text_claims = tuple(
        claim
        for name in ("title",)
        if (claim := _claim(raw, normalized, name)) is not None
    )
    return evaluate_eligibility(
        profile,
        EligibilityOpportunity(
            regions=_claim(raw, normalized, "regions"),
            estimated_amount=_claim(raw, normalized, "estimated_amount"),
            currency=_claim(raw, normalized, "currency"),
            required_certifications=_claim(raw, normalized, "required_certifications"),
            text_fields=text_claims,
        ),
    )


def _ranking(
    profile: EligibilityProfile,
    normalized: NormalizedOpportunityInput,
    eligibility: EligibilityDecision,
    *,
    as_of: datetime,
) -> RankingDecision:
    ranking_profile = RankingProfile(
        industries=profile.industries,
        capabilities=profile.capabilities,
        min_contract_amount=profile.min_contract_amount,
        max_contract_amount=profile.max_contract_amount,
        contract_currency=profile.contract_currency,
    )
    opportunity = RankingOpportunity(
        title=normalized.title,
        body=" ".join(normalized.required_capabilities),
        category=normalized.procurement_type,
        required_capabilities=normalized.required_capabilities,
        estimated_amount=normalized.estimated_amount,
        currency=normalized.currency,
        published_at=normalized.published_at,
        deadline=normalized.closes_at,
    )
    gate = RankingEligibility(
        eligibility.eligible,
        tuple(reason.code for reason in eligibility.hard_failures),
        tuple(reason.code for reason in eligibility.warnings),
    )
    return rank_opportunity(ranking_profile, opportunity, gate, as_of=as_of)


def _eligibility_payload(decision: EligibilityDecision) -> dict[str, Any]:
    return {
        "eligible": decision.eligible,
        "allows_recommendation": decision.allows_recommendation,
        "hard_failure_codes": [reason.code for reason in decision.hard_failures],
        "warning_codes": [reason.code for reason in decision.warnings],
    }


def _ranking_payload(decision: RankingDecision) -> dict[str, Any]:
    return {
        "score": float(decision.final_score),
        "recommended": decision.recommended,
        "features": {key: float(value) for key, value in decision.features.items()},
        "eligibility_gate": decision.explanation["eligibility_gate"],
    }


def _document_projection(record: RawSourceRecord) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    content = document_html(record)
    sha = hashlib.sha256(content).hexdigest()
    stored = StoredAttachment(
        sha256=sha,
        byte_size=len(content),
        media_type="text/html",
        filename="synthetic-notice.html",
        storage_key=f"synthetic/{sha}",
        original_bytes=content,
    )
    parsed = parse_document(stored)
    bundle = DocumentBundle(
        pages=tuple(
            DocumentPage(
                attachment_sha256=sha,
                page_number=page.page_number,
                text=page.text,
                parser_kind=parsed.parser_kind,
                parser_version=parsed.parser_version,
            )
            for page in parsed.pages
        )
    )
    extraction = asyncio.run(DeterministicExtractor().extract(bundle))
    validation = validate_extraction(extraction, bundle)
    return (
        {
            "parser_kind": parsed.parser_kind,
            "parser_version": parsed.parser_version,
            "page_count": parsed.page_count,
            "text_sha256": parsed.text_sha256,
        },
        extraction.output,
        {
            "valid": validation.valid,
            "errors": validation.errors,
            "trusted_fields": (
                validation.fields.model_dump(mode="json", exclude_none=True)
                if validation.fields is not None
                else {}
            ),
        },
    )


def _empty_stage(stage_id: str, *, status: StageStatus = "not_run", notice: str | None = None) -> PipelineStage:
    for candidate_id, label, kind in _STAGE_DEFINITIONS:
        if candidate_id == stage_id:
            return PipelineStage(
                id=candidate_id,
                label=label,
                kind=kind,
                status=status,
                measured_duration_ms=None,
                notice=notice,
            )
    raise KeyError(stage_id)


def _new_opportunity() -> PipelineScenario:
    anchor = datetime(2026, 9, 16, tzinfo=UTC)
    source_id = UUID(int=101)
    source = demo_records("control-room", anchor, source_id)[1]
    raw = _raw_record(source, source_id=source_id, raw_id=UUID(int=201))
    normalized = normalize_raw_record(raw)
    profile = EligibilityProfile(
        regions=("Seoul",),
        certifications=("ISO 27001",),
        min_contract_amount=Decimal("10000000"),
        max_contract_amount=Decimal("500000000"),
        contract_currency="KRW",
        excluded_keywords=(),
        industries=("services",),
        capabilities=("cloud migration", "document processing"),
    )
    eligibility = _eligibility(profile, raw, normalized)
    ranking = _ranking(profile, normalized, eligibility, as_of=anchor)
    parsed, extracted, validation = _document_projection(source)
    stages = (
        PipelineStage(
            "collect",
            "수집",
            "system",
            "passed",
            input={"source": "packaged synthetic fixture"},
            output={"source_record_id": source.source_record_id},
            evidence=({"source_url": source.source_url, "synthetic": True},),
            measured_duration_ms=None,
            notice="합성 시나리오 · 외부 네트워크 호출 없음",
        ),
        PipelineStage(
            "dedupe",
            "중복 제거",
            "system",
            "passed",
            input={"payload_sha256": raw.payload_sha256},
            output={"duplicate": False, "dedupe_key": [str(raw.source_id), raw.source_record_id, raw.payload_sha256]},
            measured_duration_ms=None,
        ),
        PipelineStage(
            "normalize",
            "정규화",
            "deterministic",
            "passed",
            input={"source_record_id": raw.source_record_id},
            output={
                "title": normalized.title,
                "lifecycle_stage": normalized.lifecycle_stage,
                "estimated_amount": str(normalized.estimated_amount),
                "currency": normalized.currency,
                "regions": list(normalized.regions),
            },
            evidence=({"normalized_sha256": normalized.normalized_sha256},),
            measured_duration_ms=None,
        ),
        PipelineStage(
            "documents",
            "문서 파싱",
            "system",
            "passed",
            input={"media_type": "text/html"},
            output=parsed,
            measured_duration_ms=None,
        ),
        PipelineStage(
            "ocr-route",
            "OCR 라우팅",
            "ocr",
            "not_run",
            input={"native_parser_status": "parsed"},
            decision={"route_to_ocr": False},
            measured_duration_ms=None,
            notice="HTML native parsing 품질이 충분해 OCR을 실행하지 않았습니다.",
        ),
        PipelineStage(
            "extract",
            "구조화 추출",
            "deterministic",
            "passed",
            input={"extractor": "deterministic-labels-v1"},
            output=extracted,
            measured_duration_ms=None,
            notice="로컬 deterministic extractor · hosted LLM 호출 없음",
        ),
        PipelineStage(
            "validate",
            "스키마·근거 검증",
            "deterministic",
            "passed" if validation["valid"] else "blocked",
            input={"schema_version": "1"},
            output=validation,
            decision={"trusted": validation["valid"]},
            measured_duration_ms=None,
        ),
        PipelineStage(
            "lifecycle",
            "생애주기 연결",
            "deterministic",
            "passed",
            input={"stage": "tender"},
            output={"link_state": "initial_tender", "official_reference_count": len(normalized.official_references)},
            measured_duration_ms=None,
        ),
        _empty_stage("delta", notice="최초 관측 버전에는 비교 대상이 없습니다."),
        PipelineStage(
            "eligibility",
            "참여 조건",
            "deterministic",
            "passed",
            output=_eligibility_payload(eligibility),
            decision={"hard_gate": "allowed" if eligibility.allows_recommendation else "blocked"},
            measured_duration_ms=None,
        ),
        PipelineStage(
            "ranking",
            "관련도 순위",
            "deterministic",
            "passed",
            output=_ranking_payload(ranking),
            decision={"eligibility_overrides_rank": True},
            measured_duration_ms=None,
        ),
        PipelineStage(
            "notification",
            "알림 판단",
            "notification",
            "passed",
            input={"watched": False, "recommended": ranking.recommended},
            output={"trigger": "new_high_relevance" if ranking.recommended else None},
            decision={"external_delivery": False},
            measured_duration_ms=None,
            notice="알림 트리거 판단만 재생하며 외부 메시지를 보내지 않습니다.",
        ),
    )
    return PipelineScenario(
        "new-opportunity",
        "신규 공고",
        "수집부터 추천·알림 판단까지",
        True,
        "packaged_fixture",
        stages,
    )


def _amendment() -> PipelineScenario:
    anchor = datetime(2026, 9, 16, tzinfo=UTC)
    source_id = UUID(int=102)
    records = demo_records("control-room", anchor, source_id)
    before_source = records[1]
    after_payload = dict(records[2].raw_payload)
    after_payload["regions"] = ["Busan"]
    after_source = records[2].model_copy(update={"raw_payload": after_payload})

    before_raw = _raw_record(before_source, source_id=source_id, raw_id=UUID(int=202))
    after_raw = _raw_record(after_source, source_id=source_id, raw_id=UUID(int=203))
    before_normalized = normalize_raw_record(before_raw)
    after_normalized = normalize_raw_record(after_raw)

    opportunity_id = UUID(int=301)
    before_version = _version(
        before_normalized,
        opportunity_id=opportunity_id,
        version_id=UUID(int=302),
        raw_id=before_raw.id,
        version_number=1,
    )
    after_version = _version(
        after_normalized,
        opportunity_id=opportunity_id,
        version_id=UUID(int=303),
        raw_id=after_raw.id,
        version_number=2,
    )
    delta = compute_delta(
        DeltaSnapshot(before_version, before_raw),
        DeltaSnapshot(after_version, after_raw),
    )

    profile = EligibilityProfile(
        regions=("Seoul",),
        certifications=("ISO 27001",),
        min_contract_amount=Decimal("10000000"),
        max_contract_amount=Decimal("500000000"),
        contract_currency="KRW",
        excluded_keywords=(),
        industries=("services",),
        capabilities=("cloud migration", "document processing"),
    )
    before_eligibility = _eligibility(profile, before_raw, before_normalized)
    after_eligibility = _eligibility(profile, after_raw, after_normalized)
    before_ranking = _ranking(profile, before_normalized, before_eligibility, as_of=anchor)
    after_ranking = _ranking(profile, after_normalized, after_eligibility, as_of=anchor)

    parsed, extracted, validation = _document_projection(after_source)

    stages = (
        PipelineStage(
            "collect",
            "수집",
            "system",
            "passed",
            input={"source_record_id": before_source.source_record_id},
            output={"observed_revision": after_source.source_record_id, "amendment": True},
            evidence=({"synthetic": True, "source_url": after_source.source_url},),
            measured_duration_ms=None,
            notice="합성 정정 시나리오 · 외부 네트워크 호출 없음",
        ),
        PipelineStage(
            "dedupe",
            "중복 제거",
            "system",
            "passed",
            input={"before_sha256": before_raw.payload_sha256, "after_sha256": after_raw.payload_sha256},
            output={"duplicate": False, "new_version_required": True},
            measured_duration_ms=None,
        ),
        PipelineStage(
            "normalize",
            "정규화",
            "deterministic",
            "passed",
            output={
                "before": before_normalized.normalized_json,
                "after": after_normalized.normalized_json,
            },
            measured_duration_ms=None,
        ),
        PipelineStage(
            "documents",
            "문서 파싱",
            "system",
            "passed",
            input={"media_type": "text/html"},
            output=parsed,
            measured_duration_ms=None,
        ),
        PipelineStage(
            "ocr-route",
            "OCR 라우팅",
            "ocr",
            "not_run",
            input={"native_parser_status": "parsed"},
            decision={"route_to_ocr": False},
            measured_duration_ms=None,
            notice="HTML native parsing 경로이므로 OCR은 실행하지 않았습니다.",
        ),
        PipelineStage(
            "extract",
            "구조화 추출",
            "deterministic",
            "passed",
            input={"extractor": "deterministic-labels-v1"},
            output=extracted,
            measured_duration_ms=None,
            notice="hosted LLM이 아닌 재현 가능한 로컬 추출 경로입니다.",
        ),
        PipelineStage(
            "validate",
            "스키마·근거 검증",
            "deterministic",
            "passed" if validation["valid"] else "blocked",
            output=validation,
            decision={"trusted": validation["valid"]},
            measured_duration_ms=None,
        ),
        PipelineStage(
            "lifecycle",
            "생애주기 연결",
            "deterministic",
            "passed",
            input={"before_stage": "tender", "after_stage": "amendment"},
            output={"same_opportunity": True, "version_transition": "tender → amendment"},
            decision={"link_method": "same source record identity"},
            measured_duration_ms=None,
        ),
        PipelineStage(
            "delta",
            "Delta",
            "deterministic",
            "passed",
            input={"from_version": 1, "to_version": 2},
            output={
                "changed_fields": delta.field_changes_json,
                "document_changes": delta.document_changes_json,
            },
            evidence=tuple(
                evidence
                for change in delta.field_changes_json.values()
                for side in ("before_evidence", "after_evidence")
                for evidence in change.get(side, [])
            ),
            decision={
                "impact": delta.impact_level,
                "reason_codes": list(delta.impact_reasons_json.get("codes", [])),
            },
            measured_duration_ms=None,
        ),
        PipelineStage(
            "eligibility",
            "참여 조건",
            "deterministic",
            "passed",
            output={
                "before": _eligibility_payload(before_eligibility),
                "after": _eligibility_payload(after_eligibility),
            },
            decision={
                "changed": before_eligibility.allows_recommendation
                != after_eligibility.allows_recommendation,
                "rule": "hard eligibility precedes relevance",
            },
            measured_duration_ms=None,
        ),
        PipelineStage(
            "ranking",
            "관련도 순위",
            "deterministic",
            "passed",
            output={
                "before": _ranking_payload(before_ranking),
                "after": _ranking_payload(after_ranking),
            },
            decision={
                "eligibility_overrides_rank": True,
                "after_score_still_visible": float(after_ranking.final_score),
            },
            measured_duration_ms=None,
        ),
        PipelineStage(
            "notification",
            "알림 판단",
            "notification",
            "passed",
            input={"watched": True, "material_change": delta.impact_level == "high"},
            output={"trigger": "watched_material_change"},
            decision={
                "should_enqueue": delta.impact_level == "high",
                "external_delivery": False,
            },
            measured_duration_ms=None,
            notice="관심 공고의 material change 알림 판단을 재생합니다. 외부 메시지는 보내지 않습니다.",
        ),
    )
    return PipelineScenario(
        "amendment-eligibility-change",
        "정정으로 조건 변경",
        "버전 변경이 Delta와 참여 가능 여부에 미치는 영향",
        True,
        "packaged_fixture",
        stages,
    )


def _failure_recovery() -> PipelineScenario:
    stages: list[PipelineStage] = []
    for stage_id, label, kind in _STAGE_DEFINITIONS:
        if stage_id == "collect":
            stages.append(
                PipelineStage(
                    stage_id,
                    label,
                    kind,
                    "warning",
                    input={"scope": "http_transport_injection"},
                    output={"transport_cases": [dict(row) for row in _FAILURE_CASES]},
                    decision={
                        "retryable": ["timeout", "429", "5xx"],
                        "non_retryable": ["403"],
                        "terminal_after_bounded_attempts": True,
                    },
                    measured_duration_ms=None,
                    notice="합성 HTTP transport 주입 결과",
                )
            )
        else:
            stages.append(
                PipelineStage(
                    stage_id,
                    label,
                    kind,
                    "blocked",
                    measured_duration_ms=None,
                    notice="수집 실패 경계를 설명하는 시나리오이므로 후속 처리를 실행하지 않습니다.",
                )
            )
    return PipelineScenario(
        "failure-recovery",
        "장애와 복구",
        "재시도·비재시도·종료 실패 경계를 확인",
        True,
        "committed_verification_artifact",
        tuple(stages),
    )


_BUILDERS = {
    "new-opportunity": _new_opportunity,
    "amendment-eligibility-change": _amendment,
    "failure-recovery": _failure_recovery,
}


def build_scenario(scenario_id: str) -> PipelineScenario:
    try:
        builder = _BUILDERS[scenario_id]
    except KeyError as error:
        raise KeyError("unknown pipeline scenario") from error
    return builder()
