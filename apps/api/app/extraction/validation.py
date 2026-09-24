"""Conservative, field-specific labeled-text grounding; unsupported prose fails closed."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.extraction.schemas import (
    DocumentBundle,
    ExtractionResult,
    GroundingCode,
    GroundingIssue,
    StructuredFields,
    ValidationReport,
)

GROUNDING_VERSION = "explicit-labels-v2"

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
    "용역명": "Title",
    "입찰건명": "Title",
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
FORM_PREFIX = re.compile(r"^(?:[ㆍ·•○ㅇ□▪-]\s*|(?:\d{1,2}|[가-하])[.)]\s*)")
# Deliberately broader than accepted label prefixes: ambiguous section-like
# starts must not become a value simply because a preceding label is empty.
VALUE_BOUNDARY = re.compile(
    r"^(?:[\[({（【〔①-⑳Ⅰ-Ⅻⅰ-ⅻ*※▷▶◆■]|[A-Za-z][.)]|[IVXLCDM]+[.)])"
)
NOTICE_HEADING = re.compile(
    r"(?:(용역|물품|공사)(?:입찰공고|입찰설명서|소액수의\(견적제출\)설명서)"
    r"|조달물자\((용역|물품|공사)\)구매입찰공고)"
)
PROCUREMENT_TYPES = {"용역": "services", "물품": "goods", "공사": "works"}


def split_label(text: str) -> tuple[str, str, bool]:
    """Normalize label typography only; keep every value and evidence quote intact."""
    parts = re.split(r"[:：]", text, maxsplit=1)
    if len(parts) != 2:
        return "", "", False
    label, value = parts
    label = FORM_PREFIX.sub("", label.strip(), count=1).strip()
    compact = "".join(label.split())
    korean = compact in KOREAN_LABELS
    return KOREAN_LABELS[compact] if korean else label, value.strip(), korean


def evidence_spans(text: str) -> Iterator[str]:
    """Single lines, or a colon-only label and its immediately adjacent value line.

    Never cross a blank line, section marker, other label, page or attachment.
    Longer wrapped values and unlabeled table cells remain unsupported.
    """
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        quote = line.strip()
        label, value, _ = split_label(quote)
        if label in {*LABELS, "Budget"} and not value and index + 1 < len(lines):
            following = lines[index + 1].strip()
            if (
                following
                and len(following) <= 300
                and not re.search(r"[:：]", following)
                and not FORM_PREFIX.match(following)
                and not VALUE_BOUNDARY.match(following)
                and "".join(following.split()) not in KOREAN_LABELS
                and following not in {*LABELS, "Budget"}
                and not NOTICE_HEADING.fullmatch("".join(following.split()))
            ):
                yield (line + lines[index + 1]).strip()
                continue
        yield quote


def labeled_claims(line: str) -> dict[str, Any]:
    """Decode one complete explicit label. Never infer values from unrelated prose."""
    heading = NOTICE_HEADING.fullmatch("".join(line.split()))
    if heading:
        return {"procurement_type": PROCUREMENT_TYPES[heading[1] or heading[2]]}
    label, value, korean = split_label(line)
    if not label or not value:
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
    issues: dict[tuple[str | None, GroundingCode], GroundingIssue] = {}

    def issue(field: str | None, code: GroundingCode) -> None:
        # Callers pass schema-validated claim names, or None for document issues.
        # Deduplication bounds published diagnostics even for repeated references.
        issues[(field, code)] = GroundingIssue.model_validate({"field": field, "code": code})

    claims = fields.model_dump(exclude_none=True, exclude={"schema_version", "evidence"})
    page_spans = [(page, list(evidence_spans(page.text))) for page in document.pages]
    for _, spans in page_spans:
        for quote in spans:
            label, value, _ = split_label(quote)
            field = LABELS.get(label)
            if field in claims and field in LIST_FIELDS and NEGATED_REQUIREMENT.search(value):
                errors.append(f"{field}: negated or qualified requirement needs review")
                issue(field, "qualified_requirement")
    for field, value in claims.items():
        references = fields.evidence.get(field, [])
        if not references:
            errors.append(f"{field}: missing evidence")
            issue(field, "missing_evidence")
        for reference in references:
            pages = [
                spans
                for page, spans in page_spans
                if (
                    page.attachment_sha256 == reference.attachment_sha256
                    and page.page_number == reference.page_number
                )
            ]
            if not any(reference.quote in spans for spans in pages):
                errors.append(f"{field}: evidence not on referenced page")
                issue(field, "evidence_not_on_page")
            if labeled_claims(reference.quote).get(field) != value:
                errors.append(f"{field}: value unsupported by labeled evidence")
                issue(field, "unsupported_value")
        observed = [
            labeled_claims(line)[field]
            for _, spans in page_spans
            for line in spans
            if field in labeled_claims(line)
        ]
        if any(item != value for item in observed):
            errors.append(f"{field}: contradictory document claims")
            issue(field, "contradictory_claims")
    if set(fields.evidence) - set(claims):
        errors.append("evidence for absent or unknown fields")
        issue(None, "evidence_for_absent_field")
    return ValidationReport(valid=not errors, errors=errors, fields=fields if not errors else None,
                            grounding_issues=list(issues.values()))
