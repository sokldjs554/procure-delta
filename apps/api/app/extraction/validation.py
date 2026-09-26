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

GROUNDING_VERSION = "explicit-labels-v4"

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
HEADING_BRACKETS = (("(", ")"), ("[", "]"), ("（", "）"), ("［", "］"))
QUOTATION_BRACKETS = {"「": "」", "『": "』", "“": "”", '"': '"', "[": "]", "［": "］"}
_ESTIMATE = "(?:" + "|".join(
    re.escape(left) + "견적제출" + re.escape(right) for left, right in HEADING_BRACKETS
) + ")"
_CATEGORY = "(?:" + "|".join(
    re.escape(left) + "(용역|물품|공사)" + re.escape(right)
    for left, right in HEADING_BRACKETS
) + ")"
NOTICE_HEADING = re.compile(
    rf"(?:(용역|물품|공사)(?:입찰공고|입찰설명서|소액수의{_ESTIMATE}설명서)"
    rf"|조달물자{_CATEGORY}구매입찰공고)"
)
PROCUREMENT_TYPES = {"용역": "services", "물품": "goods", "공사": "works"}
AMOUNT_LITERAL = r"-?[0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?"
# Identify explicit ISO-shaped literals only. A parse failure within this shape
# must remain an invalid claim; prose and genuinely unsupported formats stay absent.
ISO_DATETIME_LITERAL = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:[.,][0-9]+)?)?"
    r"(?:Z|[+-][0-9]{2}:?[0-9]{2}| KST)?)?"
)


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


def _value_line(text: str) -> bool:
    return bool(
        text
        and len(text) <= 300
        and not re.search(r"[:：]", text)
        and not FORM_PREFIX.match(text)
        and not VALUE_BOUNDARY.match(text)
        and "".join(text.split()) not in KOREAN_LABELS
        and text not in {*LABELS, "Budget"}
        and not NOTICE_HEADING.fullmatch("".join(text.split()))
    )


def _title_quote_end(value: str) -> int | None:
    """Find the outer closing mark, preserving nested title punctuation."""
    closing = QUOTATION_BRACKETS.get(value[:1])
    if not closing:
        return None
    opening = value[0]
    depth = 1
    for index, character in enumerate(value[1:], start=1):
        if character == closing:
            depth -= 1
            if depth == 0:
                return index
        elif character == opening:
            depth += 1
    return None


def _whole_title_quote(value: str) -> bool:
    return bool(value) and _title_quote_end(value) == len(value) - 1


def _title_value(value: str) -> str:
    if _whole_title_quote(value):
        return " ".join(value[1:-1].split())
    closing = QUOTATION_BRACKETS.get(value[:1])
    if closing and _title_quote_end(value) is None:
        # Keep the malformed claim visible to schema/conflict validation, even if
        # another valid title occurs first. Never accept a truncated quoted title.
        return ""
    return value


def _joined_heading(first: str, second: str) -> str | None:
    joined = (first + second).strip()
    if first.strip() and second.strip() and len(joined) <= 120 and NOTICE_HEADING.fullmatch(
        "".join(joined.split())
    ):
        return joined
    return None


def evidence_spans(text: str) -> Iterator[str]:
    """Exact single-line or bounded adjacent two-line form spans.

    Never cross a blank line, section marker, other label, page or attachment.
    Only a complete heading or an explicitly enclosed title can join beyond the
    existing colon-only label rule. Unquoted wrapped values remain unsupported.
    """
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        quote = line.strip()
        label, value, _ = split_label(quote)
        if index + 1 < len(lines):
            following = lines[index + 1].strip()
            joined = (line + lines[index + 1]).strip()
            heading = _joined_heading(line, lines[index + 1])
            if heading:
                yield heading
                continue
            following_heading = (
                index + 2 < len(lines)
                and _joined_heading(lines[index + 1], lines[index + 2]) is not None
            )
            joined_value = split_label(joined)[1]
            if (
                label == "Title" and value and not _title_value(value)
                and _value_line(following) and len(joined_value) <= 300
                and _whole_title_quote(joined_value)
            ):
                yield joined
                continue
            if (
                label in {*LABELS, "Budget"} and not value
                and not following_heading and _value_line(following)
            ):
                yield joined
                continue
        yield quote


def labeled_claims(line: str) -> dict[str, Any]:
    """Decode one complete explicit label. Never infer values from unrelated prose."""
    heading = NOTICE_HEADING.fullmatch("".join(line.split()))
    if heading:
        kind = next(value for value in heading.groups() if value is not None)
        return {"procurement_type": PROCUREMENT_TYPES[kind]}
    label, value, korean = split_label(line)
    if not label or not value:
        return {}
    if label == "Budget":
        if korean and re.fullmatch(AMOUNT_LITERAL + "원", value):
            value = "KRW " + value[:-1]
        match = re.fullmatch(r"(KRW|USD|EUR|JPY) (" + AMOUNT_LITERAL + ")", value)
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
                    # Valid date-only deadlines remain unsupported. An impossible
                    # calendar date is invalid, not merely missing a time/zone.
                    datetime.fromisoformat(value)
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
            # As with invalid ISO contract periods, preserve the literal so the
            # schema/source-constraint check rejects it even if a model omits it.
            return {field: value} if ISO_DATETIME_LITERAL.fullmatch(value) else {}
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
        dates = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?: to |/)(\d{4}-\d{2}-\d{2})", value)
        # Relative/free-form periods are unsupported, not guessed date ranges.
        # Explicit ISO-shaped dates still reach the schema, including invalid ones.
        return {field: f"{dates[1]}/{dates[2]}"} if dates else {}
    if field == "title":
        return {field: _title_value(value)}
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
    observed: dict[str, list[Any]] = {}
    qualified: set[str] = set()
    for _, spans in page_spans:
        for quote in spans:
            label, value, _ = split_label(quote)
            field = LABELS.get(label)
            if field in LIST_FIELDS and NEGATED_REQUIREMENT.search(value):
                qualified.add(field)
                if field in claims:
                    errors.append(f"{field}: negated or qualified requirement needs review")
                    issue(field, "qualified_requirement")
            for source_field, source_value in labeled_claims(quote).items():
                observed.setdefault(source_field, []).append(source_value)

    # Validate supported source constraints independently of the model's selection.
    # Otherwise omitting an invalid budget, reversed dates or a conflicting optional
    # field could turn the same document from rejected into trusted. This is only a
    # rejection check: do not add source fields to the returned model proposal.
    source_values = {}
    for field, values in observed.items():
        if field in qualified and field not in claims:
            # The existing contract explicitly permits whole-field omission here.
            continue
        source_values[field] = values[0]
        if any(value != values[0] for value in values[1:]):
            errors.append(f"{field}: contradictory document claims")
            issue(field, "contradictory_claims")
    try:
        StructuredFields.model_validate({
            **claims, **source_values, "schema_version": fields.schema_version, "evidence": {},
        })
    except ValidationError as error:
        errors.append("document: invalid explicit source claim")
        for item in error.errors(include_input=False, include_context=False, include_url=False):
            name = item["loc"][0] if item["loc"] else None
            issue(name if isinstance(name, str) and name in source_values else None,
                  "invalid_source_claim")
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
        if any(item != value for item in observed.get(field, [])):
            errors.append(f"{field}: contradictory document claims")
            issue(field, "contradictory_claims")
    if set(fields.evidence) - set(claims):
        errors.append("evidence for absent or unknown fields")
        issue(None, "evidence_for_absent_field")
    return ValidationReport(valid=not errors, errors=errors, fields=fields if not errors else None,
                            grounding_issues=list(issues.values()))
