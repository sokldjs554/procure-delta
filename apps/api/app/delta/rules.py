from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

RULESET_VERSION = "delta-v1"


@dataclass(frozen=True)
class ImpactAssessment:
    level: str
    reason_codes: tuple[str, ...]


def classify_impact(changes: dict[str, Any]) -> ImpactAssessment:
    """Versioned business rules, independent of explanations and the wall clock."""
    reasons: dict[str, int] = {}
    for field, change in changes.items():
        if field == "attachments":
            for item in change:
                kind = item["kind"]
                reasons[f"attachment_{kind}"] = 0 if kind == "added" else 1
            continue
        before, after = change["before"], change["after"]
        if before is None or after is None:
            reasons[f"{field}_became_unknown" if after is None else f"{field}_became_known"] = 1
        elif field == "budget":
            if before["currency"] != after["currency"]:
                reasons["budget_currency_changed"] = 1
            elif Decimal(after["estimated_amount"]) > Decimal(before["estimated_amount"]):
                reasons["budget_increased"] = 1
            else:
                reasons["budget_decreased"] = 1
        elif field == "closes_at":
            earlier = after < before  # canonical UTC ISO values
            reasons["deadline_earlier" if earlier else "deadline_later"] = 2 if earlier else 1
        elif field == "regions":
            kind = "added" if not before else "removed" if not after else "changed"
            reasons[f"region_restriction_{kind}"] = 1 if kind == "removed" else 2
        elif field in {"required_certifications", "required_capabilities"}:
            prefix = "certification" if field == "required_certifications" else "capability"
            if set(after) - set(before):
                reasons[f"{prefix}_added"] = 2
            if set(before) - set(after):
                reasons[f"{prefix}_removed"] = 1
        elif field == "participation_constraints":
            reasons["material_clause_changed"] = 2
        elif field == "contract_period":
            reasons["contract_period_changed"] = 1
    return ImpactAssessment(
        level=("low", "medium", "high")[max(reasons.values(), default=0)],
        reason_codes=tuple(sorted(reasons)),
    )
