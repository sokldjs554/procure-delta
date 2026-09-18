from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.extraction.base import StructuredExtractor
from app.extraction.hosted import configured_extractor
from app.extraction.service import (
    build_document_bundle,
    extraction_identity,
    trusted_extraction_view,
)
from app.models import (
    CompanyProfile,
    EligibilityResult,
    OpportunityVersion,
    RawRecord,
    StructuredExtraction,
)

RULESET_VERSION = "hard-eligibility-v1"


@dataclass(frozen=True)
class EvidenceClaim:
    field: str
    value: Any
    evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class EligibilityProfile:
    regions: tuple[str, ...] = ()
    certifications: tuple[str, ...] = ()
    min_contract_amount: Decimal | None = None
    max_contract_amount: Decimal | None = None
    contract_currency: str | None = None
    excluded_keywords: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class EligibilityOpportunity:
    regions: EvidenceClaim | None = None
    estimated_amount: EvidenceClaim | None = None
    currency: EvidenceClaim | None = None
    required_certifications: EvidenceClaim | None = None
    text_fields: tuple[EvidenceClaim, ...] = ()


@dataclass(frozen=True)
class EligibilityReason:
    code: str
    field: str
    message: str
    evidence: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    hard_failures: tuple[EligibilityReason, ...]
    warnings: tuple[EligibilityReason, ...]

    @property
    def needs_review(self) -> bool:
        return bool(self.warnings)

    @property
    def allows_recommendation(self) -> bool:
        """The downstream ranking gate; scores cannot change this value."""
        return self.eligible and not self.needs_review


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _reason(code: str, claim: EvidenceClaim | None, message: str, field: str) -> EligibilityReason:
    return EligibilityReason(code, field, message, claim.evidence if claim else ())


def evaluate_eligibility(
    profile: EligibilityProfile, opportunity: EligibilityOpportunity
) -> EligibilityDecision:
    hard: list[EligibilityReason] = []
    warnings: list[EligibilityReason] = []

    if opportunity.regions is None:
        warnings.append(
            _reason("region_unknown", None, "Opportunity region is unknown.", "regions")
        )
    elif not profile.regions:
        warnings.append(
            _reason(
                "profile_regions_unknown",
                opportunity.regions,
                "Company service regions are not configured.",
                "regions",
            )
        )
    elif not {_norm(item) for item in profile.regions}.intersection(
        _norm(str(item)) for item in opportunity.regions.value
    ):
        hard.append(
            _reason(
                "region_not_served",
                opportunity.regions,
                "Opportunity region is outside the company service regions.",
                "regions",
            )
        )

    bounds_exist = (
        profile.min_contract_amount is not None or profile.max_contract_amount is not None
    )
    if bounds_exist and opportunity.estimated_amount is None:
        warnings.append(
            _reason("amount_unknown", None, "Opportunity amount is unknown.", "estimated_amount")
        )
    elif bounds_exist and opportunity.currency is None:
        warnings.append(
            _reason("amount_currency_unknown", None, "Opportunity currency is unknown.", "currency")
        )
    elif bounds_exist and profile.contract_currency is None:
        warnings.append(
            _reason(
                "profile_currency_unknown",
                opportunity.currency,
                "Company contract currency is not configured.",
                "currency",
            )
        )
    elif bounds_exist:
        assert opportunity.currency is not None
        assert opportunity.estimated_amount is not None
        if str(opportunity.currency.value).upper() != profile.contract_currency:
            warnings.append(
                _reason(
                    "amount_currency_mismatch",
                    opportunity.currency,
                    "Amount bounds use a different currency; no conversion was invented.",
                    "currency",
                )
            )
        else:
            amount = Decimal(str(opportunity.estimated_amount.value))
            if profile.min_contract_amount is not None and amount < profile.min_contract_amount:
                hard.append(
                    _reason(
                        "amount_below_minimum",
                        opportunity.estimated_amount,
                        "Opportunity amount is below the company minimum.",
                        "estimated_amount",
                    )
                )
            if profile.max_contract_amount is not None and amount > profile.max_contract_amount:
                hard.append(
                    _reason(
                        "amount_above_maximum",
                        opportunity.estimated_amount,
                        "Opportunity amount is above the company maximum.",
                        "estimated_amount",
                    )
                )

    if opportunity.required_certifications is None:
        warnings.append(
            _reason(
                "certifications_unknown",
                None,
                "Required certifications are unknown.",
                "required_certifications",
            )
        )
    else:
        owned = {_norm(item) for item in profile.certifications}
        missing = [
            str(item)
            for item in opportunity.required_certifications.value
            if _norm(str(item)) not in owned
        ]
        if missing:
            hard.append(
                _reason(
                    "missing_certification",
                    opportunity.required_certifications,
                    f"Missing required certification: {', '.join(sorted(missing))}.",
                    "required_certifications",
                )
            )

    for keyword in profile.excluded_keywords:
        needle = _norm(keyword)
        for text_claim in opportunity.text_fields:
            values = text_claim.value if isinstance(text_claim.value, list) else [text_claim.value]
            pattern = rf"(?<!\w){re.escape(needle)}(?!\w)"
            if any(re.search(pattern, _norm(str(value))) for value in values):
                hard.append(
                    _reason(
                        "explicit_exclusion",
                        text_claim,
                        f"Matched company excluded keyword: {keyword}.",
                        text_claim.field,
                    )
                )
                break

    return EligibilityDecision(not hard, tuple(hard), tuple(warnings))


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _raw_claim(raw: RawRecord, version: OpportunityVersion, field: str) -> EvidenceClaim | None:
    value = version.normalized_json.get(field)
    if value is None or value == [] or value == "":
        return None
    raw_backed = field in raw.payload_json and raw.payload_json[field] not in (None, [], "")
    evidence = {
        "kind": "raw" if raw_backed else "normalized",
        "raw_record_id": str(raw.id),
        "source_id": str(raw.source_id),
        "source_record_id": raw.source_record_id,
        "payload_sha256": raw.payload_sha256,
    }
    if raw_backed:
        evidence["json_pointer"] = f"/{field}"
    else:
        mapped = version.normalized_json.get("evidence", {}).get(field, [])
        if mapped and isinstance(mapped[0], dict):
            pointer = mapped[0].get("json_pointer")
            if (
                mapped[0].get("normalizer") == "koneps-services-v1"
                and isinstance(pointer, str)
                and pointer.startswith("/")
                and raw.payload_json.get(pointer[1:]) not in (None, "", [])
            ):
                evidence.update(kind="raw", json_pointer=pointer, normalizer="koneps-services-v1")
                return EvidenceClaim(field, value, (evidence,))
        evidence.update(
            {
                "version_id": str(version.id),
                "normalized_sha256": version.normalized_sha256,
                "field": field,
            }
        )
    return EvidenceClaim(
        field,
        value,
        (evidence,),
    )


async def _prepared_opportunity(
    session: AsyncSession,
    version: OpportunityVersion,
    extractor: StructuredExtractor | None = None,
) -> tuple[EligibilityOpportunity, dict[str, Any]]:
    raw = await session.get_one(RawRecord, version.raw_record_id)
    document = await build_document_bundle(session, version.id)
    current_extractor = extractor or configured_extractor(get_settings())
    current_key = extraction_identity(document, current_extractor)
    extraction = await session.scalar(
        select(StructuredExtraction).where(
            StructuredExtraction.opportunity_version_id == version.id,
            StructuredExtraction.validation_status == "validated",
            StructuredExtraction.input_fingerprint == document.fingerprint,
            StructuredExtraction.extraction_key == current_key,
        )
    )
    view = None
    extraction_id = None
    if extraction is not None:
        candidate = await trusted_extraction_view(session, extraction.id)
        if candidate is not None:
            view, extraction_id = candidate, extraction.id

    def trusted_claim(field: str) -> EvidenceClaim | None:
        direct = _raw_claim(raw, version, field)
        if direct is not None:
            return direct
        if view is None or field not in view.fields:
            return None
        return EvidenceClaim(
            field,
            view.fields[field],
            tuple({"kind": "attachment_claim", **item} for item in view.evidence.get(field, [])),
        )

    upstream_amount = _raw_claim(raw, version, "estimated_amount")
    upstream_currency = _raw_claim(raw, version, "currency")
    amount: EvidenceClaim | None
    currency: EvidenceClaim | None
    if upstream_amount is not None and upstream_currency is not None:
        amount, currency = upstream_amount, upstream_currency
    elif upstream_amount is None and upstream_currency is None and view is not None:
        extracted_amount = view.fields.get("estimated_amount")
        extracted_currency = view.fields.get("currency")
        if extracted_amount is not None and extracted_currency is not None:
            amount = EvidenceClaim(
                "estimated_amount",
                extracted_amount,
                tuple(
                    {"kind": "attachment_claim", **item}
                    for item in view.evidence.get("estimated_amount", [])
                ),
            )
            currency = EvidenceClaim(
                "currency",
                extracted_currency,
                tuple(
                    {"kind": "attachment_claim", **item}
                    for item in view.evidence.get("currency", [])
                ),
            )
        else:
            amount = currency = None
    else:
        amount = currency = None
    text_claims = (
        trusted_claim("title"),
        trusted_claim("description"),
        trusted_claim("body"),
        trusted_claim("participation_constraints"),
    )
    text_fields = tuple(
        filter(
            None,
            text_claims,
        )
    )
    prepared = EligibilityOpportunity(
        trusted_claim("regions"),
        amount,
        currency,
        trusted_claim("required_certifications"),
        text_fields,
    )
    provenance = {
        "version_id": str(version.id),
        "raw_record_id": str(raw.id),
        "normalized_sha256": version.normalized_sha256,
        "extraction_id": str(extraction_id) if extraction_id else None,
        "extraction_key": current_key,
        "extraction_input_fingerprint": document.fingerprint if extraction_id else None,
        "claims": asdict(prepared),
        "ranking_claims": {
            "title": asdict(text_claims[0]) if text_claims[0] else None,
            "description": asdict(text_claims[1]) if text_claims[1] else None,
            "body": asdict(text_claims[2]) if text_claims[2] else None,
            "category": asdict(claim) if (claim := trusted_claim("procurement_type")) else None,
            "required_capabilities": asdict(claim)
            if (claim := trusted_claim("required_capabilities"))
            else None,
            "estimated_amount": asdict(amount) if amount else None,
            "currency": asdict(currency) if currency else None,
            "published_at": asdict(claim) if (claim := trusted_claim("published_at")) else None,
            "deadline": asdict(claim) if (claim := trusted_claim("closes_at")) else None,
        },
    }
    return prepared, provenance


async def materialize_eligibility(
    session: AsyncSession,
    company_profile_id: UUID,
    opportunity_version_id: UUID,
    *,
    extractor: StructuredExtractor | None = None,
) -> EligibilityResult:
    version = await session.get_one(OpportunityVersion, opportunity_version_id)
    profile_row = await session.scalar(
        select(CompanyProfile).where(CompanyProfile.id == company_profile_id).with_for_update()
    )
    if profile_row is None:
        raise LookupError("company profile not found")
    profile = EligibilityProfile(
        regions=tuple(profile_row.regions),
        certifications=tuple(profile_row.certifications),
        min_contract_amount=profile_row.min_contract_amount,
        max_contract_amount=profile_row.max_contract_amount,
        contract_currency=profile_row.contract_currency,
        excluded_keywords=tuple(profile_row.excluded_keywords),
        industries=tuple(profile_row.industries),
        capabilities=tuple(profile_row.capabilities),
    )
    prepared, opportunity_provenance = await _prepared_opportunity(session, version, extractor)
    profile_data = _jsonable(asdict(profile))
    profile_fingerprint = _hash(profile_data)
    opportunity_fingerprint = _hash(opportunity_provenance)
    existing = await session.scalar(
        select(EligibilityResult).where(
            EligibilityResult.company_profile_id == company_profile_id,
            EligibilityResult.opportunity_version_id == opportunity_version_id,
            EligibilityResult.ruleset_version == RULESET_VERSION,
            EligibilityResult.profile_input_fingerprint == profile_fingerprint,
            EligibilityResult.opportunity_input_fingerprint == opportunity_fingerprint,
        )
    )
    if existing is not None:
        return existing
    decision = evaluate_eligibility(profile, prepared)
    row = EligibilityResult(
        company_profile_id=company_profile_id,
        opportunity_version_id=opportunity_version_id,
        eligible=decision.eligible,
        hard_fail_reasons_json=_jsonable(
            {"items": [asdict(item) for item in decision.hard_failures]}
        ),
        warnings_json=_jsonable({"items": [asdict(item) for item in decision.warnings]}),
        ruleset_version=RULESET_VERSION,
        profile_input_fingerprint=profile_fingerprint,
        opportunity_input_fingerprint=opportunity_fingerprint,
        input_provenance_json=_jsonable(
            {"profile": profile_data, "opportunity": opportunity_provenance}
        ),
    )
    session.add(row)
    await session.flush()
    return row
