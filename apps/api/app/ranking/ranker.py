from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EligibilityResult, OpportunityVersion, RankingResult
from app.ranking.features import (
    RankingOpportunity,
    RankingProfile,
    amount_score,
    capability_score,
    category_score,
    lexical_score,
    recency_deadline_score,
)

RANKING_VERSION = "deterministic-baseline-v1"
RECOMMENDATION_THRESHOLD = Decimal("0.60")
MAX_SEMANTIC_CANDIDATES = 20
_QUANT = Decimal("0.00001")
_WEIGHTS = {
    "lexical": Decimal("0.25"),
    "capability": Decimal("0.25"),
    "category": Decimal("0.20"),
    "amount": Decimal("0.15"),
    "recency_deadline": Decimal("0.15"),
}


class SemanticReranker:
    """Optional bounded experiment interface; baseline operation never calls it."""

    max_candidates = MAX_SEMANTIC_CANDIDATES

    def score(self, profile: RankingProfile, opportunity: RankingOpportunity) -> Decimal:
        raise NotImplementedError


@dataclass(frozen=True)
class RankingEligibility:
    eligible: bool
    hard_failure_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]

    @property
    def allows_recommendation(self) -> bool:
        return self.eligible and not self.hard_failure_codes and not self.warning_codes


@dataclass(frozen=True)
class RankingDecision:
    features: dict[str, Decimal]
    feature_score: Decimal
    semantic_score: Decimal | None
    final_score: Decimal
    recommended: bool
    explanation: dict[str, Any]


def _bounded(value: Decimal) -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), value)).quantize(_QUANT)


def rank_opportunity(
    profile: RankingProfile,
    opportunity: RankingOpportunity,
    eligibility: RankingEligibility,
    *,
    as_of: datetime,
    semantic_reranker: SemanticReranker | None = None,
    semantic_enabled: bool = False,
) -> RankingDecision:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    amount, amount_reason = amount_score(profile, opportunity)
    features = {
        "lexical": _bounded(lexical_score(profile, opportunity)),
        "capability": _bounded(capability_score(profile, opportunity)),
        "category": _bounded(category_score(profile, opportunity)),
        "amount": _bounded(amount),
        "recency_deadline": _bounded(recency_deadline_score(opportunity, as_of)),
    }
    feature_score = _bounded(
        sum(
            (features[name] * weight for name, weight in _WEIGHTS.items()),
            start=Decimal("0"),
        )
    )
    semantic_score = None
    final_score = feature_score
    if semantic_enabled and semantic_reranker is not None:
        if not 1 <= semantic_reranker.max_candidates <= MAX_SEMANTIC_CANDIDATES:
            raise ValueError("semantic reranker candidate bound must be between 1 and 20")
        semantic_score = _bounded(semantic_reranker.score(profile, opportunity))
        final_score = _bounded(feature_score * Decimal("0.80") + semantic_score * Decimal("0.20"))
    deadline_state = (
        "unknown"
        if opportunity.deadline is None
        else "open"
        if opportunity.deadline >= as_of
        else "expired"
    )
    recommended = (
        eligibility.allows_recommendation
        and deadline_state != "expired"
        and final_score >= RECOMMENDATION_THRESHOLD
    )
    explanation: dict[str, Any] = {
        "ranking_version": RANKING_VERSION,
        "as_of": as_of.isoformat(),
        "weights": {key: str(value) for key, value in _WEIGHTS.items()},
        "feature_reasons": {"amount": amount_reason},
        "evidence": opportunity.evidence,
        "eligibility_gate": "allowed" if eligibility.allows_recommendation else "blocked",
        "eligibility_hard_failures": list(eligibility.hard_failure_codes),
        "eligibility_warnings": list(eligibility.warning_codes),
        "semantic_enabled": semantic_enabled,
        "deadline_state": deadline_state,
    }
    return RankingDecision(
        features, feature_score, semantic_score, final_score, recommended, explanation
    )


def _parse_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _codes(payload: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(item["code"]) for item in payload.get("items", []) if "code" in item)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


async def materialize_ranking(
    session: AsyncSession,
    eligibility_result_id: UUID,
    *,
    as_of: datetime,
    require_current: bool = True,
    evaluation_epoch: str | None = None,
) -> RankingResult:
    eligibility_row = await session.get(EligibilityResult, eligibility_result_id)
    if eligibility_row is None:
        raise LookupError("eligibility result not found")
    version = await session.get_one(OpportunityVersion, eligibility_row.opportunity_version_id)
    if require_current:
        from app.ranking.eligibility import materialize_eligibility

        current = await materialize_eligibility(
            session, eligibility_row.company_profile_id, version.id
        )
        if current.id != eligibility_row.id:
            raise ValueError("eligibility result is stale; rank the current input revision")
    eligibility_row = await session.scalar(
        select(EligibilityResult)
        .where(EligibilityResult.id == eligibility_result_id)
        .with_for_update()
    )
    assert eligibility_row is not None
    provenance = eligibility_row.input_provenance_json.get("opportunity", {})
    if provenance.get("version_id") != str(version.id):
        raise ValueError("eligibility provenance does not identify the ranked version")
    if provenance.get("normalized_sha256") != version.normalized_sha256:
        raise ValueError("eligibility provenance is stale for the ranked version")
    if version.effective_at > as_of:
        raise ValueError("opportunity version was not available at as_of")
    profile_snapshot = eligibility_row.input_provenance_json.get("profile")
    if not isinstance(profile_snapshot, dict) or not {
        "industries",
        "capabilities",
    }.issubset(profile_snapshot):
        raise ValueError("eligibility result lacks immutable ranking profile inputs")
    profile = RankingProfile(
        tuple(profile_snapshot["industries"]),
        tuple(profile_snapshot["capabilities"]),
        Decimal(str(profile_snapshot["min_contract_amount"]))
        if profile_snapshot.get("min_contract_amount") is not None
        else None,
        Decimal(str(profile_snapshot["max_contract_amount"]))
        if profile_snapshot.get("max_contract_amount") is not None
        else None,
        profile_snapshot.get("contract_currency"),
    )
    claims = provenance.get("ranking_claims", {})
    if not isinstance(claims, dict):
        raise ValueError("eligibility result lacks authoritative ranking claims")

    def claim_value(field: str) -> Any:
        claim = claims.get(field)
        return claim.get("value") if isinstance(claim, dict) else None

    evidence = {
        field: value.get("evidence", [])
        for field, value in claims.items()
        if isinstance(value, dict) and value.get("evidence")
    }
    opportunity = RankingOpportunity(
        title=str(claim_value("title") or ""),
        body=str(claim_value("description") or claim_value("body") or ""),
        category=claim_value("category"),
        required_capabilities=tuple(claim_value("required_capabilities") or ()),
        estimated_amount=Decimal(str(claim_value("estimated_amount")))
        if claim_value("estimated_amount") is not None
        else None,
        currency=claim_value("currency"),
        published_at=_parse_datetime(claim_value("published_at")),
        deadline=_parse_datetime(claim_value("deadline")),
        evidence=evidence,
    )
    eligibility = RankingEligibility(
        eligibility_row.eligible,
        _codes(eligibility_row.hard_fail_reasons_json),
        _codes(eligibility_row.warnings_json),
    )
    decision = rank_opportunity(profile, opportunity, eligibility, as_of=as_of)
    epoch = evaluation_epoch or f"exact:{as_of.isoformat()}"
    if epoch.startswith("daily:"):
        daily_bucket = ":".join(epoch.split(":")[:2])
        expected_bucket = f"daily:{as_of.astimezone(UTC).date().isoformat()}"
        if daily_bucket != expected_bucket:
            raise ValueError("daily evaluation epoch must match the UTC as_of date")
        epoch = f"{daily_bucket}:{decision.explanation['deadline_state']}"
    input_identity = {
        "eligibility_result_id": str(eligibility_row.id),
        "eligibility_ruleset_version": eligibility_row.ruleset_version,
        "profile_input_fingerprint": eligibility_row.profile_input_fingerprint,
        "opportunity_input_fingerprint": eligibility_row.opportunity_input_fingerprint,
        "version_id": str(version.id),
        "normalized_sha256": version.normalized_sha256,
        "evaluation_epoch": epoch,
    }
    input_fingerprint = _hash(input_identity)
    existing = await session.scalar(
        select(RankingResult).where(
            RankingResult.company_profile_id == eligibility_row.company_profile_id,
            RankingResult.opportunity_version_id == version.id,
            RankingResult.ranking_version == RANKING_VERSION,
            RankingResult.input_fingerprint == input_fingerprint,
        )
    )
    if existing is not None:
        return existing
    input_provenance = {**input_identity, "decision_as_of": as_of.isoformat()}
    row = RankingResult(
        company_profile_id=eligibility_row.company_profile_id,
        opportunity_version_id=version.id,
        eligibility_result_id=eligibility_row.id,
        lexical_score=decision.features["lexical"],
        semantic_score=decision.semantic_score,
        feature_score=decision.feature_score,
        rerank_score=decision.semantic_score,
        final_score=decision.final_score,
        recommended=decision.recommended,
        feature_breakdown_json={key: str(value) for key, value in decision.features.items()},
        explanation_json=decision.explanation,
        input_fingerprint=input_fingerprint,
        input_provenance_json=input_provenance,
        as_of=as_of,
        evaluation_epoch=epoch,
        ranking_version=RANKING_VERSION,
    )
    session.add(row)
    await session.flush()
    return row
