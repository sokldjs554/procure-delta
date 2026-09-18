from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.delta.rules import RULESET_VERSION, classify_impact
from app.extraction.service import TrustedExtractionView
from app.models import Attachment, OpportunityDelta, OpportunityVersion, RawRecord

FIELDS = (
    "closes_at",
    "regions",
    "required_certifications",
    "required_capabilities",
    "participation_constraints",
    "contract_period",
)
SET_FIELDS = {
    "regions",
    "required_certifications",
    "required_capabilities",
    "participation_constraints",
}


@dataclass(frozen=True)
class DeltaSnapshot:
    version: OpportunityVersion
    raw: RawRecord
    attachments: tuple[Attachment, ...] = ()
    extraction: TrustedExtractionView | None = None
    attachment_manifest_complete: bool = True


def _claim(snapshot: DeltaSnapshot, field: str) -> tuple[Any, list[dict[str, Any]]]:
    raw, version = snapshot.raw, snapshot.version
    value = version.normalized_json.get(field)
    evidence: list[dict[str, Any]] = []
    # Normalizer defaults are not affirmative upstream claims of absence.
    if field in raw.payload_json and raw.payload_json[field] is not None:
        evidence = [
            {
                "kind": "raw",
                "raw_record_id": str(raw.id),
                "source_id": str(raw.source_id),
                "source_record_id": raw.source_record_id,
                "payload_sha256": raw.payload_sha256,
                "json_pointer": f"/{field}",
            }
        ]
    elif snapshot.extraction is not None and field in snapshot.extraction.fields:
        value = snapshot.extraction.fields[field]
        evidence = [
            {"kind": "attachment_claim", **item}
            for item in snapshot.extraction.evidence.get(field, [])
        ]
    elif field == "currency" and raw.payload_json.get("estimated_amount") is not None:
        value = version.normalized_json.get("currency", "KRW")
        evidence = [
            {
                "kind": "normalizer_default",
                "field": "currency",
                "value": value,
                "raw_record_id": str(raw.id),
                "normalizer": version.extraction_version,
            }
        ]
    else:
        value = None
    if value is not None:
        if field in SET_FIELDS:
            value = sorted(set(value))
        elif field == "estimated_amount":
            value = format(Decimal(str(value)).normalize(), "f")
        elif field == "closes_at":
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("deadline must have a timezone")
            value = parsed.astimezone(UTC).isoformat()
    return value, evidence


def _budget(snapshot: DeltaSnapshot) -> tuple[Any, list[dict[str, Any]]]:
    amount, amount_evidence = _claim(snapshot, "estimated_amount")
    currency, currency_evidence = _claim(snapshot, "currency")
    # Never combine attachment money with a default/upstream currency independently.
    if snapshot.raw.payload_json.get("estimated_amount") is None and snapshot.extraction:
        amount = snapshot.extraction.fields.get("estimated_amount")
        currency = snapshot.extraction.fields.get("currency")
        amount_evidence = [
            {"kind": "attachment_claim", **item}
            for item in snapshot.extraction.evidence.get("estimated_amount", [])
        ]
        currency_evidence = [
            {"kind": "attachment_claim", **item}
            for item in snapshot.extraction.evidence.get("currency", [])
        ]
        if amount is not None:
            amount = format(Decimal(str(amount)).normalize(), "f")
    if amount is None or currency is None:
        return None, []
    return {"estimated_amount": amount, "currency": currency}, amount_evidence + currency_evidence


def _attachment_value(item: Attachment) -> dict[str, Any]:
    return {"source_url": item.source_url, "filename": item.filename, "sha256": item.sha256}


def _attachment_evidence(item: Attachment | None) -> list[dict[str, Any]]:
    return (
        []
        if item is None
        else [
            {
                "kind": "attachment",
                "attachment_id": str(item.id),
                "version_id": str(item.opportunity_version_id),
                "source_url": item.source_url,
                "sha256": item.sha256,
            }
        ]
    )


def compute_delta(before: DeltaSnapshot, after: DeltaSnapshot) -> OpportunityDelta:
    """Compare immutable version inputs; persistence/readiness is the service's job."""
    if before.version.opportunity_id != after.version.opportunity_id:
        raise ValueError("versions must belong to the same opportunity")
    if before.version.version_number >= after.version.version_number:
        raise ValueError("versions must be in ascending observation order")
    for snapshot in (before, after):
        if snapshot.raw.id != snapshot.version.raw_record_id:
            raise ValueError("raw provenance must match version")
    fields = {}
    for field in ("budget", *FIELDS):
        old, old_evidence = _budget(before) if field == "budget" else _claim(before, field)
        new, new_evidence = _budget(after) if field == "budget" else _claim(after, field)
        if old != new:
            fields[field] = {
                "before": old,
                "after": new,
                "before_evidence": old_evidence,
                "after_evidence": new_evidence,
            }
    old_manifest = {item.source_url: item for item in before.attachments}
    new_manifest = {item.source_url: item for item in after.attachments}
    documents = []
    for url in sorted(old_manifest.keys() | new_manifest.keys()):
        old_item, new_item = old_manifest.get(url), new_manifest.get(url)
        if old_item is None and not before.attachment_manifest_complete:
            continue
        if new_item is None and not after.attachment_manifest_complete:
            continue
        old_value = _attachment_value(old_item) if old_item else None
        new_value = _attachment_value(new_item) if new_item else None
        if old_item and new_item and (old_item.sha256 is None or new_item.sha256 is None):
            continue  # A failed download does not prove replacement of content.
        if old_value != new_value:
            documents.append(
                {
                    "kind": "added"
                    if old_item is None
                    else "removed"
                    if new_item is None
                    else "replaced",
                    "before": old_value,
                    "after": new_value,
                    "before_evidence": _attachment_evidence(old_item),
                    "after_evidence": _attachment_evidence(new_item),
                }
            )
    impact = classify_impact({**fields, "attachments": documents})
    return OpportunityDelta(
        opportunity_id=after.version.opportunity_id,
        from_version_id=before.version.id,
        to_version_id=after.version.id,
        field_changes_json=fields,
        document_changes_json={"attachments": documents} if documents else {},
        impact_level=impact.level,
        impact_reasons_json={"codes": list(impact.reason_codes), "ruleset": RULESET_VERSION},
    )


def explain_delta(result: OpportunityDelta, generator: Callable[[dict[str, Any]], str]) -> str:
    """Optional prose is separate from, and cannot mutate, the authoritative result."""
    return generator(
        deepcopy(
            {
                "field_changes": result.field_changes_json,
                "document_changes": result.document_changes_json,
                "impact_level": result.impact_level,
                "impact_reasons": result.impact_reasons_json,
            }
        )
    )
