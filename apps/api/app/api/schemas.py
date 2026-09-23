"""API contracts: explicit resource fields; JSON values only for versioned pipeline payloads."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.provenance import PublicJSON, public_validation_errors


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Reason(DTO):
    code: str
    field: str
    message: str
    evidence: list[PublicJSON]


class Eligibility(DTO):
    id: UUID
    eligible: bool
    hard_failures: list[Reason]
    warnings: list[Reason]
    ruleset_version: str


class Ranking(DTO):
    id: UUID
    recommended: bool
    final_score: Decimal
    features: dict[str, Decimal]
    explanation: PublicJSON
    as_of: datetime
    evaluation_epoch: str
    ranking_version: str


class OpportunitySummary(DTO):
    id: UUID
    title: str
    buyer_name: str
    procurement_type: str | None
    lifecycle_stage: str | None
    estimated_amount: Decimal | None
    currency: str
    published_at: datetime | None
    closes_at: datetime | None
    status: str | None
    current_version_id: UUID | None
    eligibility: Eligibility | None = None
    ranking: Ranking | None = None
    watched: bool = False
    changed_at: datetime | None = None
    decision_status: Literal[
        "profile_required", "missing_version", "documents_pending", "future_version", "ready"
    ] = "profile_required"


class OpportunityPage(DTO):
    items: list[OpportunitySummary]
    next_cursor: str | None


class Version(DTO):
    id: UUID
    version_number: int
    source_record_id: str
    effective_at: datetime
    transition_kind: str
    created_at: datetime
    normalized_json: PublicJSON


class Link(DTO):
    id: UUID
    parent_opportunity_id: UUID
    child_opportunity_id: UUID
    parent_version_id: UUID | None
    child_version_id: UUID | None
    relation_type: str
    confidence: Decimal
    link_method: str
    status: str
    evidence_json: PublicJSON
    created_at: datetime
    retracted_at: datetime | None


class Timeline(DTO):
    opportunity_ids: list[UUID]
    active_links: list[Link]
    historical_links: list[Link]


class ContractProcessSnapshotSummary(DTO):
    id: UUID
    opportunity_version_id: UUID
    inquiry_div: str
    page_no: int
    total_count: int
    response_sha256: str
    identifiers: PublicJSON
    fetched_at: datetime


class ContractProcessHistory(DTO):
    items: list[ContractProcessSnapshotSummary]


class Parse(DTO):
    id: UUID
    parser_kind: str
    parser_version: str
    status: str
    page_count: int | None
    # Native parse quality is explicitly NOT structured extraction trust.
    quality_json: PublicJSON


class Document(DTO):
    id: UUID
    filename: str
    media_type: str | None
    sha256: str | None
    byte_size: int | None
    download_status: str
    original_url: str | None
    parses: list[Parse]


class Extraction(DTO):
    status: str
    id: UUID | None = None
    extractor_version: str | None = None
    schema_version: str | None = None
    input_fingerprint: str | None = None
    trusted_fields: PublicJSON = Field(default_factory=dict)
    evidence: PublicJSON = Field(default_factory=dict)
    conflicts: PublicJSON = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)

    @field_validator("validation_errors")
    @classmethod
    def safe_errors(cls, value: list[str]) -> list[str]:
        return public_validation_errors(value)


class Delta(DTO):
    id: UUID
    from_version_id: UUID
    to_version_id: UUID
    field_changes_json: PublicJSON
    document_changes_json: PublicJSON
    impact_level: str
    impact_reasons_json: PublicJSON
    comparison_kind: str
    created_at: datetime
    applicable_now: bool


class ExtractionSnapshot(Extraction):
    applicable_now: bool
    proposal: PublicJSON


class DeltaHistory(DTO):
    items: list[Delta]
    current_inputs_ready: bool


class OpportunityDetail(OpportunitySummary):
    versions: list[Version]
    timeline: Timeline
    deltas: DeltaHistory
    documents: list[Document]
    extraction: Extraction


class WatchState(DTO):
    opportunity_id: UUID
    watched: Literal[True] = True


class Notification(DTO):
    id: UUID
    opportunity_id: UUID
    delta_id: UUID | None
    channel: str
    template_key: str
    status: str
    attempt_count: int
    next_attempt_at: datetime | None
    sent_at: datetime | None
    payload: PublicJSON
    receipt_id: UUID | None
    received_at: datetime | None


class NotificationPage(DTO):
    items: list[Notification]
    next_cursor: str | None
