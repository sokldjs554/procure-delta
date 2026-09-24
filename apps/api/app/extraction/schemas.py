from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentPage(StrictModel):
    attachment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1)
    text: str
    parser_kind: str
    parser_version: str


class DocumentBundle(StrictModel):
    pages: tuple[DocumentPage, ...]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class Evidence(StrictModel):
    attachment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1)


class StructuredFields(StrictModel):
    schema_version: Literal["1"]
    buyer_name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    procurement_type: Literal["services", "goods", "works"]
    estimated_amount: Decimal | None = Field(
        default=None, gt=0, le=Decimal("9999999999999999.99"), decimal_places=2
    )
    currency: Literal["KRW", "USD", "EUR", "JPY"] | None = None
    published_at: AwareDatetime | None = None
    closes_at: AwareDatetime | None = None
    regions: list[str] | None = None
    required_certifications: list[str] | None = None
    required_capabilities: list[str] | None = None
    participation_constraints: list[str] | None = None
    contract_period: str | None = None
    evidence: dict[str, list[Evidence]]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.published_at and self.closes_at and self.closes_at < self.published_at:
            raise ValueError("closing date precedes publication")
        if (self.estimated_amount is None) != (self.currency is None):
            raise ValueError("amount and currency must be supplied together")
        if self.contract_period:
            from datetime import date

            start, end = self.contract_period.split("/")
            if date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError("contract end precedes start")
        claims = self.model_dump(exclude_none=True, exclude={"schema_version", "evidence"})
        if not claims:
            raise ValueError("no extracted claims")
        for value in claims.values():
            if isinstance(value, list) and (
                not value
                or any(not item.strip() for item in value)
                or len(set(value)) != len(value)
            ):
                raise ValueError("lists must contain distinct nonblank values")
        return self


ResponseStatus = Literal[
    "parsed", "invalid_json", "invalid_envelope", "non_object_json",
    "refused", "incomplete_response",
]
ResponseFinishReason = Literal[
    "stop", "length", "content_filter", "tool_calls", "function_call", "other"
]


class HostedResponseDiagnostics(StrictModel):
    """Bounded metadata only; never upstream text, arbitrary values or headers."""

    http_status: int = Field(ge=100, le=599)
    status: ResponseStatus = "invalid_envelope"
    content_format: Literal["plain", "json_fence", "non_text"] | None = None
    finish_reason: ResponseFinishReason | None = None
    usage_status: Literal["reported", "partial", "missing"] = "missing"


class ExtractionResult(StrictModel):
    """A proposal: construction does not confer business-field trust."""

    output: dict[str, Any]
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    diagnostics: HostedResponseDiagnostics | None = None


GroundingField = Literal[
    "buyer_name", "title", "procurement_type", "estimated_amount", "currency",
    "published_at", "closes_at", "regions", "required_certifications",
    "required_capabilities", "participation_constraints", "contract_period",
]
GroundingCode = Literal[
    "missing_evidence", "evidence_not_on_page", "unsupported_value",
    "contradictory_claims", "qualified_requirement", "evidence_for_absent_field",
]


class GroundingIssue(StrictModel):
    """Publishable labels only; never include rejected values or source text."""

    field: GroundingField | None
    code: GroundingCode


class ValidationReport(StrictModel):
    valid: bool
    errors: list[str]
    fields: StructuredFields | None = None
    grounding_issues: list[GroundingIssue] = Field(default_factory=list)
