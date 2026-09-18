"""Conservative, field-specific labeled-text grounding; unsupported prose fails closed."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.extraction.schemas import (
    DocumentBundle,
    ExtractionResult,
    StructuredFields,
    ValidationReport,
)

LABELS = {
    "Title": "title",
    "Buyer": "buyer_name",
    "Category": "procurement_type",
    "Published": "published_at",
    "Deadline": "closes_at",
    "Region": "regions",
    "Certifications": "required_certifications",
    "Capabilities": "required_capabilities",
    "Participation constraints": "participation_constraints",
    "Contract period": "contract_period",
}
LIST_FIELDS = {
    "regions",
    "required_certifications",
    "required_capabilities",
    "participation_constraints",
}
KOREAN_LABELS = {
    "공고명": "Title",
    "사업명": "Title",
    "수요기관": "Buyer",
    "발주기관": "Buyer",
    "분류": "Category",
    "계약구분": "Category",
    "추정가격": "Budget",
    "예산": "Budget",
    "공고일": "Published",
    "마감일": "Deadline",
    "입찰마감일": "Deadline",
    "지역": "Region",
    "필수인증": "Certifications",
    "필수역량": "Capabilities",
    "참가자격": "Participation constraints",
    "계약기간": "Contract period",
}
NEGATED_REQUIREMENT = re.compile(
    r"\b(not|no|without|optional|except)\b|미보유|불필요|제외|선택", re.I
)


def labeled_claims(line: str) -> dict[str, Any]:
    """Decode one complete explicit label. Never infer values from unrelated prose."""
    label, separator, value = line.strip().partition(":")
    korean = label in KOREAN_LABELS
    label = KOREAN_LABELS.get(label, label)
    value = value.strip()
    if not separator or not value:
        return {}
    if label == "Budget":
        if korean and re.fullmatch(r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?원", value):
            value = "KRW " + value[:-1]
        match = re.fullmatch(r"(KRW|USD|EUR|JPY) ([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)", value)
        if not match:
            return {}
        return {"currency": match[1], "estimated_amount": Decimal(match[2].replace(",", ""))}
    field = LABELS.get(label)
    if field is None:
        return {}
    if field in LIST_FIELDS:
        items = [item.strip() for item in value.split(";")]
        # Do not turn a negated requirement into a positive eligibility claim.
        if any(NEGATED_REQUIREMENT.search(item) for item in items):
            return {}
        return {field: items}
    if field in {"published_at", "closes_at"}:
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                if field != "published_at":
                    return {}
                parsed = (
                    datetime.fromisoformat(value + "T00:00:00+09:00")
                    if korean
                    else datetime.fromisoformat(value).replace(tzinfo=UTC)
                )
            else:
                parsed = datetime.fromisoformat(
                    value.replace(" KST", "+09:00").replace("Z", "+00:00")
                )
            if parsed.tzinfo is None:
                return {}
            return {field: parsed.astimezone(UTC)}
        except ValueError:
            return {}
    if field == "procurement_type":
        return {
            field: {
                "IT services": "services",
                "용역": "services",
                "물품": "goods",
                "공사": "works",
            }.get(value, value)
        }
    if field == "contract_period":
        return {field: value.replace(" to ", "/")}
    return {field: value}


def validate_extraction(result: ExtractionResult, document: DocumentBundle) -> ValidationReport:
    try:
        fields = StructuredFields.model_validate(result.output)
    except ValidationError as error:
        return ValidationReport(valid=False, errors=[str(error)])
    errors: list[str] = []
    claims = fields.model_dump(exclude_none=True, exclude={"schema_version", "evidence"})
    for page in document.pages:
        for line in page.text.splitlines():
            label, _, value = line.strip().partition(":")
            field = LABELS.get(KOREAN_LABELS.get(label, label))
            if field in claims and field in LIST_FIELDS and NEGATED_REQUIREMENT.search(value):
                errors.append(f"{field}: negated or qualified requirement needs review")
    for field, value in claims.items():
        references = fields.evidence.get(field, [])
        if not references:
            errors.append(f"{field}: missing evidence")
        for reference in references:
            pages = [
                page
                for page in document.pages
                if (
                    page.attachment_sha256 == reference.attachment_sha256
                    and page.page_number == reference.page_number
                )
            ]
            if not any(
                reference.quote in [line.strip() for line in page.text.splitlines()]
                for page in pages
            ):
                errors.append(f"{field}: evidence not on referenced page")
            if labeled_claims(reference.quote).get(field) != value:
                errors.append(f"{field}: value unsupported by labeled evidence")
        observed = [
            labeled_claims(line)[field]
            for page in document.pages
            for line in page.text.splitlines()
            if field in labeled_claims(line)
        ]
        if any(item != value for item in observed):
            errors.append(f"{field}: contradictory document claims")
    if set(fields.evidence) - set(claims):
        errors.append("evidence for absent or unknown fields")
    return ValidationReport(valid=not errors, errors=errors, fields=fields if not errors else None)
