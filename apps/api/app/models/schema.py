from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKey:
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)


class SourceRegistry(UUIDPrimaryKey, Base):
    __tablename__ = "source_registry"
    code: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    base_url: Mapped[str] = mapped_column(String(2048))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    polling_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestRun(UUIDPrimaryKey, Base):
    __tablename__ = "ingest_runs"
    source_id: Mapped[UUID] = mapped_column(ForeignKey("source_registry.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50))
    cursor_before: Mapped[str | None] = mapped_column(Text)
    cursor_after: Mapped[str | None] = mapped_column(Text)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)


class RawRecord(UUIDPrimaryKey, Base):
    __tablename__ = "raw_records"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "source_record_id",
            "payload_sha256",
            name="uq_raw_record_payload",
        ),
    )
    source_id: Mapped[UUID] = mapped_column(ForeignKey("source_registry.id"), index=True)
    source_record_id: Mapped[str] = mapped_column(String(255))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    http_etag: Mapped[str | None] = mapped_column(String(255))
    http_last_modified: Mapped[str | None] = mapped_column(String(255))
    schema_version: Mapped[str] = mapped_column(String(50), default="1")
    normalization_status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    normalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    normalized_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("opportunity_versions.id", use_alter=True)
    )


class Opportunity(UUIDPrimaryKey, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["opportunity_versions.opportunity_id", "opportunity_versions.id"],
            name="fk_opportunity_current_version",
            use_alter=True,
        ),
        Index("ix_opportunities_stage_published", "lifecycle_stage", "published_at"),
    )
    canonical_key: Mapped[str] = mapped_column(String(255), unique=True)
    title: Mapped[str] = mapped_column(Text)
    buyer_name: Mapped[str] = mapped_column(String(255))
    procurement_type: Mapped[str | None] = mapped_column(String(100))
    lifecycle_stage: Mapped[str | None] = mapped_column(String(100), index=True)
    estimated_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str | None] = mapped_column(String(50))
    current_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    current_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OpportunityVersion(UUIDPrimaryKey, Base):
    __tablename__ = "opportunity_versions"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "version_number", name="uq_opportunity_version_number"),
        UniqueConstraint("opportunity_id", "id", name="uq_opportunity_version_owner"),
    )
    opportunity_id: Mapped[UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    raw_record_id: Mapped[UUID] = mapped_column(ForeignKey("raw_records.id"), unique=True)
    version_number: Mapped[int] = mapped_column(Integer)
    source_record_id: Mapped[str] = mapped_column(String(255))
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    normalized_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    normalized_sha256: Mapped[str] = mapped_column(String(64))
    extraction_version: Mapped[str | None] = mapped_column(String(100))
    previous_current_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("opportunity_versions.id")
    )
    transition_kind: Mapped[str] = mapped_column(String(20), server_default="unknown")
    transition_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    documents_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    documents_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    documents_generation: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    document_gaps_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LifecycleLink(UUIDPrimaryKey, Base):
    __tablename__ = "lifecycle_links"
    __table_args__ = (
        CheckConstraint(
            "parent_opportunity_id <> child_opportunity_id", name="ck_lifecycle_link_not_self"
        ),
        Index(
            "uq_lifecycle_active_child",
            "child_opportunity_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
    parent_opportunity_id: Mapped[UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    child_opportunity_id: Mapped[UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    parent_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunity_versions.id"))
    child_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunity_versions.id"))
    relation_type: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    link_method: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Attachment(UUIDPrimaryKey, Base):
    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_version_id", "source_url", name="uq_attachment_version_source_url"
        ),
    )
    opportunity_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("opportunity_versions.id"), index=True
    )
    source_url: Mapped[str] = mapped_column(String(2048))
    filename: Mapped[str] = mapped_column(String(1024))
    media_type: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str | None] = mapped_column(String(64))
    byte_size: Mapped[int | None] = mapped_column(Integer)
    download_status: Mapped[str] = mapped_column(String(50), default="pending")
    storage_key: Mapped[str | None] = mapped_column(String(2048))


class DocumentParse(UUIDPrimaryKey, Base):
    __tablename__ = "document_parses"
    __table_args__ = (
        UniqueConstraint(
            "attachment_id", "parser_kind", "parser_version", name="uq_document_parse_version"
        ),
    )
    attachment_id: Mapped[UUID] = mapped_column(ForeignKey("attachments.id"), index=True)
    parser_kind: Mapped[str] = mapped_column(String(50))
    parser_version: Mapped[str] = mapped_column(String(100))
    text_sha256: Mapped[str | None] = mapped_column(String(64))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    quality_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(50))


class StructuredExtraction(UUIDPrimaryKey, Base):
    __tablename__ = "structured_extractions"
    __table_args__ = (
        UniqueConstraint("opportunity_version_id", "extraction_key", name="uq_extraction_identity"),
    )
    opportunity_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("opportunity_versions.id"), index=True
    )
    extractor_version: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(255))
    schema_version: Mapped[str] = mapped_column(String(50))
    extraction_key: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    input_bundle_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    conflicts_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    validation_status: Mapped[str] = mapped_column(String(50))
    validation_errors_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class CompanyProfile(UUIDPrimaryKey, Base):
    __tablename__ = "company_profiles"
    __table_args__ = (UniqueConstraint("owner_user_id", name="uq_company_profiles_owner"),)
    owner_user_id: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    synthetic_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    regions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    industries: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    certifications: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    employee_band: Mapped[str | None] = mapped_column(String(100))
    min_contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    max_contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    contract_currency: Mapped[str | None] = mapped_column(String(3))
    excluded_keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)


class EligibilityResult(UUIDPrimaryKey, Base):
    __tablename__ = "eligibility_results"
    __table_args__ = (
        UniqueConstraint(
            "company_profile_id",
            "opportunity_version_id",
            "ruleset_version",
            "profile_input_fingerprint",
            "opportunity_input_fingerprint",
            name="uq_eligibility_inputs",
        ),
    )
    company_profile_id: Mapped[UUID] = mapped_column(ForeignKey("company_profiles.id"), index=True)
    opportunity_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("opportunity_versions.id"), index=True
    )
    eligible: Mapped[bool] = mapped_column(Boolean)
    hard_fail_reasons_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    warnings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ruleset_version: Mapped[str] = mapped_column(String(100))
    profile_input_fingerprint: Mapped[str] = mapped_column(String(64))
    opportunity_input_fingerprint: Mapped[str] = mapped_column(String(64))
    input_provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RankingResult(UUIDPrimaryKey, Base):
    __tablename__ = "ranking_results"
    __table_args__ = (
        UniqueConstraint(
            "company_profile_id",
            "opportunity_version_id",
            "ranking_version",
            "input_fingerprint",
            name="uq_ranking_inputs",
        ),
    )
    company_profile_id: Mapped[UUID] = mapped_column(ForeignKey("company_profiles.id"), index=True)
    opportunity_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("opportunity_versions.id"), index=True
    )
    eligibility_result_id: Mapped[UUID | None] = mapped_column(ForeignKey("eligibility_results.id"))
    lexical_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    semantic_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    feature_score: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    rerank_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    final_score: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_breakdown_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    explanation_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    input_provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evaluation_epoch: Mapped[str] = mapped_column(String(100))
    ranking_version: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OpportunityDelta(UUIDPrimaryKey, Base):
    __tablename__ = "opportunity_deltas"
    __table_args__ = (
        UniqueConstraint(
            "from_version_id",
            "to_version_id",
            "ruleset_version",
            "input_fingerprint",
            name="uq_delta_pair_input",
        ),
        CheckConstraint("from_version_id <> to_version_id", name="ck_delta_distinct_versions"),
        ForeignKeyConstraint(
            ["opportunity_id", "from_version_id"],
            ["opportunity_versions.opportunity_id", "opportunity_versions.id"],
            name="fk_delta_from_owner",
        ),
        ForeignKeyConstraint(
            ["opportunity_id", "to_version_id"],
            ["opportunity_versions.opportunity_id", "opportunity_versions.id"],
            name="fk_delta_to_owner",
        ),
    )
    opportunity_id: Mapped[UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    from_version_id: Mapped[UUID] = mapped_column(ForeignKey("opportunity_versions.id"))
    to_version_id: Mapped[UUID] = mapped_column(ForeignKey("opportunity_versions.id"))
    field_changes_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    document_changes_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    impact_level: Mapped[str] = mapped_column(String(20))
    impact_reasons_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ruleset_version: Mapped[str] = mapped_column(String(100), server_default="legacy")
    input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    input_provenance_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    comparison_kind: Mapped[str] = mapped_column(String(30), server_default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Watchlist(UUIDPrimaryKey, Base):
    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("user_id", "opportunity_id", name="uq_watchlist_user_opportunity"),
    )
    user_id: Mapped[str] = mapped_column(String(255))
    opportunity_id: Mapped[UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationEvent(UUIDPrimaryKey, Base):
    __tablename__ = "notification_events"
    __table_args__ = (Index("ix_notification_due", "status", "next_attempt_at"),)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    opportunity_id: Mapped[UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    delta_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunity_deltas.id"))
    channel: Mapped[str] = mapped_column(String(50))
    template_key: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))


class NotificationPreference(UUIDPrimaryKey, Base):
    __tablename__ = "notification_preferences"
    user_id: Mapped[str] = mapped_column(String(255), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    channels: Mapped[list[str]] = mapped_column(ARRAY(String))
    triggers: Mapped[list[str]] = mapped_column(ARRAY(String))


class LocalNotificationReceipt(UUIDPrimaryKey, Base):
    __tablename__ = "local_notification_receipts"
    notification_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("notification_events.id"), unique=True
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JobFailure(UUIDPrimaryKey, Base):
    __tablename__ = "job_failures"
    __table_args__ = (
        UniqueConstraint("job_type", "job_key", name="uq_job_failure_type_key"),
        Index("ix_job_failures_dead_lettered_retry", "dead_lettered", "next_retry_at"),
    )
    job_type: Mapped[str] = mapped_column(String(100))
    job_key: Mapped[str] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_class: Mapped[str] = mapped_column(String(255))
    error_message: Mapped[str] = mapped_column(Text)
    last_error_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dead_lettered: Mapped[bool] = mapped_column(Boolean, default=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AuditEvent(UUIDPrimaryKey, Base):
    __tablename__ = "audit_events"
    actor_type: Mapped[str] = mapped_column(String(100))
    actor_id: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
