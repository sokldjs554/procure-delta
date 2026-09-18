from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import RawRecord


class NormalizedOpportunityInput(BaseModel):
    """Typed, source-preserving business state ready for version persistence."""

    model_config = ConfigDict(frozen=True)

    source_id: UUID
    source_record_id: str
    canonical_key: str
    title: str
    buyer_name: str
    procurement_type: str | None = None
    lifecycle_stage: str
    estimated_amount: Decimal | None = None
    currency: str = "KRW"
    published_at: datetime | None = None
    closes_at: datetime | None = None
    status: str | None = None
    effective_at: datetime
    regions: tuple[str, ...] = Field(default_factory=tuple)
    required_certifications: tuple[str, ...] = Field(default_factory=tuple)
    required_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    participation_constraints: tuple[str, ...] = Field(default_factory=tuple)
    contract_period: str | None = None
    attachments: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    evidence: dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool = False
    official_references: tuple[dict[str, str], ...] = Field(default_factory=tuple)
    normalized_identifiers: tuple[dict[str, str], ...] = Field(default_factory=tuple)
    normalized_json: dict[str, Any]
    normalized_sha256: str

    @field_validator("title", "buyer_name", "lifecycle_stage")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


def _datetime(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return parsed.astimezone(UTC)


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list of strings")
    return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))


def _linkage_values(value: object, required: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("linkage provenance must be a list")
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("linkage provenance entries must be objects")
        normalized = {name: str(item.get(name, "")).strip() for name in required}
        if any(not normalized[name] for name in required):
            raise ValueError("linkage provenance entry is missing a required value")
        result.append(normalized)
    return tuple(result)


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def normalize_raw_record(
    raw: RawRecord, *, source_code: str | None = None
) -> NormalizedOpportunityInput:
    """Map a preserved raw payload into stable, typed procurement fields."""
    payload = raw.payload_json
    if source_code == "koneps-services":
        from app.sources.koneps import map_payload

        payload = map_payload(payload, raw.source_record_id)
    try:
        title_value = payload["title"]
        buyer_value = payload["buyer_name"]
        stage_value = payload["lifecycle_stage"]
    except KeyError as error:
        raise ValueError(f"missing required normalization field: {error.args[0]}") from error
    for name, value in (
        ("title", title_value),
        ("buyer_name", buyer_value),
        ("lifecycle_stage", stage_value),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    title = title_value.strip()
    buyer_name = buyer_value.strip()
    lifecycle_stage = stage_value.strip()

    published_at = _datetime(payload.get("published_at"))
    effective_at = (
        _datetime(payload.get("effective_at"))
        or raw.source_updated_at
        or published_at
        or raw.fetched_at
    )
    if effective_at is None:
        raise ValueError("normalization requires a deterministic effective or fetched timestamp")
    amount_value = payload.get("estimated_amount")
    amount = Decimal(str(amount_value)) if amount_value is not None else None
    fields: dict[str, Any] = {
        "schema_version": "1",
        "title": title,
        "buyer_name": buyer_name,
        "procurement_type": payload.get("procurement_type"),
        "lifecycle_stage": lifecycle_stage,
        "estimated_amount": amount,
        "currency": str(payload.get("currency", "KRW")),
        "published_at": published_at,
        "closes_at": _datetime(payload.get("closes_at")),
        "status": payload.get("status"),
        "regions": _strings(payload.get("regions")),
        "required_certifications": _strings(payload.get("required_certifications")),
        "required_capabilities": _strings(payload.get("required_capabilities")),
        "participation_constraints": _strings(payload.get("participation_constraints")),
        "contract_period": payload.get("contract_period"),
        "attachments": tuple(payload.get("attachments", ())),
        "evidence": dict(payload.get("evidence", {})),
        "is_synthetic": bool(payload.get("is_synthetic", False)),
        "official_references": _linkage_values(
            payload.get("official_references"), ("source_record_id", "lifecycle_stage")
        ),
        "normalized_identifiers": _linkage_values(
            payload.get("normalized_identifiers"), ("scheme", "value")
        ),
    }
    normalized_json = cast(
        dict[str, Any],
        _json_value(
            {"source_id": str(raw.source_id), "source_record_id": raw.source_record_id, **fields}
        ),
    )
    if amount is not None:
        normalized_json["estimated_amount"] = format(amount.normalize(), "f")
    encoded = json.dumps(
        normalized_json, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    identity = str(payload.get("canonical_identity", raw.source_record_id))
    identity_hash = hashlib.sha256(identity.encode()).hexdigest()
    return NormalizedOpportunityInput(
        source_id=raw.source_id,
        source_record_id=raw.source_record_id,
        canonical_key=f"{raw.source_id}:{identity_hash}",
        effective_at=effective_at,
        normalized_json=normalized_json,
        normalized_sha256=hashlib.sha256(encoded).hexdigest(),
        **{key: value for key, value in fields.items() if key != "schema_version"},
    )
