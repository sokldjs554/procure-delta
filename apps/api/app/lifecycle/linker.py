from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Protocol
from uuid import UUID

STAGE_ORDER = {
    "pre-specification": 0,
    "tender": 1,
    "amendment": 2,
    "award": 3,
    "contract": 4,
}
GRAPH_LOCK_ID = 9020260916


@dataclass(frozen=True)
class LinkCandidate:
    opportunity_id: UUID
    source_id: UUID
    source_record_id: str
    lifecycle_stage: str
    title: str
    buyer_name: str
    estimated_amount: Decimal | None = None
    published_at: datetime | None = None
    official_references: tuple[tuple[UUID, str, str], ...] = ()
    normalized_identifiers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LinkDecision:
    status: str
    parent_opportunity_id: UUID | None = None
    method: str | None = None
    confidence: Decimal | None = None
    evidence: Mapping[str, object] | None = None
    reason: str | None = None

    @classmethod
    def resolved(
        cls,
        parent_opportunity_id: UUID,
        *,
        method: str,
        confidence: Decimal,
        evidence: Mapping[str, object],
    ) -> LinkDecision:
        return cls(
            status="resolved",
            parent_opportunity_id=parent_opportunity_id,
            method=method,
            confidence=confidence,
            evidence=evidence,
        )

    @classmethod
    def unresolved(cls, reason: str) -> LinkDecision:
        return cls(status="unresolved", reason=reason)


class SemanticComparator(Protocol):
    def compare(self, record: LinkCandidate, candidate: LinkCandidate) -> Decimal: ...


def _forward(parent: LinkCandidate, child: LinkCandidate) -> bool:
    parent_rank = STAGE_ORDER.get(parent.lifecycle_stage)
    child_rank = STAGE_ORDER.get(child.lifecycle_stage)
    return (
        parent.opportunity_id != child.opportunity_id
        and parent_rank is not None
        and child_rank is not None
        and parent_rank < child_rank
    )


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _select_unique(
    matches: Sequence[LinkCandidate],
    record: LinkCandidate,
    *,
    method: str,
    confidence: Decimal,
    evidence: Mapping[str, object] | Callable[[LinkCandidate], Mapping[str, object]],
    ambiguous_reason: str,
) -> LinkDecision:
    compatible = [item for item in matches if _forward(item, record)]
    if not compatible:
        return LinkDecision.unresolved("incompatible_stage")
    if len(compatible) != 1:
        return LinkDecision.unresolved(ambiguous_reason)
    selected = compatible[0]
    selected_evidence = evidence(selected) if callable(evidence) else evidence
    return LinkDecision.resolved(
        selected.opportunity_id,
        method=method,
        confidence=confidence,
        evidence=selected_evidence,
    )


def link_candidate(
    record: LinkCandidate,
    candidates: Sequence[LinkCandidate],
    *,
    semantic_comparator: SemanticComparator | None = None,
) -> LinkDecision:
    """Choose one conservative parent; a tie is always an unresolved decision."""
    references = record.official_references
    if references:
        matches = [
            item
            for item in candidates
            if any(
                item.source_id == source_id
                and item.source_record_id == source_record_id
                and item.lifecycle_stage == stage
                for source_id, source_record_id, stage in references
            )
        ]
        if len(references) > 1 or len(matches) > 1:
            return LinkDecision.unresolved("ambiguous_official_reference")
        if not matches:
            return LinkDecision.unresolved("official_reference_not_found")
        source_id, source_record_id, _stage = references[0]
        return _select_unique(
            matches,
            record,
            method="official_reference",
            confidence=Decimal("1.0000"),
            evidence={"source_id": str(source_id), "source_record_id": source_record_id},
            ambiguous_reason="ambiguous_official_reference",
        )

    identifiers = set(record.normalized_identifiers)
    if identifiers:
        exact = [
            item
            for item in candidates
            if item.source_id == record.source_id
            and identifiers.intersection(item.normalized_identifiers)
        ]
        if exact:
            return _select_unique(
                exact,
                record,
                method="normalized_identifier",
                confidence=Decimal("0.9900"),
                evidence=lambda selected: {
                    "source_id": str(record.source_id),
                    "scheme": sorted(identifiers.intersection(selected.normalized_identifiers))[0][
                        0
                    ],
                    "value": sorted(identifiers.intersection(selected.normalized_identifiers))[0][
                        1
                    ],
                },
                ambiguous_reason="ambiguous_normalized_identifier",
            )

    fingerprint = [
        item
        for item in candidates
        if item.source_id == record.source_id
        and SequenceMatcher(
            None, _normalized_text(item.title), _normalized_text(record.title)
        ).ratio()
        >= 0.90
        and _normalized_text(item.buyer_name) == _normalized_text(record.buyer_name)
        and item.estimated_amount is not None
        and record.estimated_amount is not None
        and item.estimated_amount == record.estimated_amount
        and item.published_at is not None
        and record.published_at is not None
        and abs(item.published_at - record.published_at) <= timedelta(days=30)
    ]
    if fingerprint:
        return _select_unique(
            fingerprint,
            record,
            method="fingerprint",
            confidence=Decimal("0.8500"),
            evidence={"fields": ["buyer_name", "title", "published_at", "estimated_amount"]},
            ambiguous_reason="ambiguous_fingerprint",
        )

    # The boundary is deliberately opt-in. It cannot override ambiguity from stronger stages.
    if semantic_comparator is not None:
        eligible = sorted(
            (
                item
                for item in candidates
                if item.source_id == record.source_id and _forward(item, record)
            ),
            key=lambda item: item.opportunity_id,
        )[:20]
        scored = [(semantic_comparator.compare(record, item), item) for item in eligible]
        bounded = [
            (score, item)
            for score, item in scored
            if score.is_finite() and Decimal("0") <= score <= Decimal("1")
        ]
        if bounded:
            best_score = max(score for score, _item in bounded)
            best = [
                item
                for score, item in bounded
                if score == best_score and score >= Decimal("0.9500")
            ]
            if len(best) == 1:
                return LinkDecision.resolved(
                    best[0].opportunity_id,
                    method="semantic",
                    confidence=best_score,
                    evidence={"bounded": True},
                )
            if len(best) > 1:
                return LinkDecision.unresolved("ambiguous_semantic")
    return LinkDecision.unresolved("no_conservative_match")
