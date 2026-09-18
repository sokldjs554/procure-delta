"""Public projections of persisted pipeline JSON, never an in-place history rewrite."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attachment

# These are product claims, evidence coordinates, and pipeline explanation/quality facts.
# Unspecified upstream/provider transport metadata is not part of the public contract.
PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "title",
        "buyer_name",
        "procurement_type",
        "lifecycle_stage",
        "estimated_amount",
        "currency",
        "published_at",
        "closes_at",
        "status",
        "regions",
        "required_certifications",
        "required_capabilities",
        "participation_constraints",
        "contract_period",
        "description",
        "body",
        "attachments",
        "evidence",
        "is_synthetic",
        "official_references",
        "normalized_identifiers",
        "source_id",
        "source_record_id",
        "raw_record_id",
        "payload_sha256",
        "json_pointer",
        "field",
        "value",
        "normalizer",
        "kind",
        "filename",
        "sha256",
        "attachment_sha256",
        "attachment_id",
        "version_id",
        "page_number",
        "quote",
        "text",
        "parser_kind",
        "parser_version",
        "scheme",
        "fields",
        "ruleset",
        "parent_version_id",
        "child_version_id",
        "bounded",
        "budget",
        "before",
        "after",
        "before_evidence",
        "after_evidence",
        "codes",
        "reason",
        "upstream",
        "attachment",
        "ranking_version",
        "as_of",
        "weights",
        "feature_reasons",
        "lexical",
        "capability",
        "category",
        "amount",
        "recency_deadline",
        "eligibility_gate",
        "eligibility_hard_failures",
        "eligibility_warnings",
        "semantic_enabled",
        "deadline_state",
        "deadline",
        "provider",
        "provider_version",
        "synthetic",
        "recognition_status",
        "pages",
        "quality",
        "reasons",
        "char_count",
        "non_whitespace_chars",
        "printable_ratio",
        "alphanumeric_ratio",
        "error",
        "ranking_result_id",
        "final_score",
        "explanation",
        "delta_id",
        "field_changes",
        "document_changes",
        "impact_level",
        "reason_codes",
        "from_version_id",
        "to_version_id",
        "outcome_opportunity_id",
        "outcome_version_id",
        "watched_opportunity_id",
        "link_ids",
    }
)


class AttachmentReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: UUID
    sha256: str | None
    original_url: str | None


class PublicProvenance:
    def __init__(self, attachments: Sequence[Attachment] = ()) -> None:
        self.attachments = attachments

    def _attachment(
        self, value: dict[str, JsonValue], version_id: UUID | None
    ) -> Attachment | None:
        identifier = value.get("attachment_id")
        if isinstance(identifier, str):
            return next((item for item in self.attachments if str(item.id) == identifier), None)
        checksum = value.get("attachment_sha256", value.get("sha256"))
        location = value.get("source_url", value.get("url"))
        if not isinstance(checksum, str) and not isinstance(location, str):
            return None
        matches = [
            item
            for item in self.attachments
            if (version_id is None or item.opportunity_version_id == version_id)
            and (not isinstance(checksum, str) or item.sha256 == checksum)
            and (not isinstance(location, str) or item.source_url == location)
        ]
        return matches[0] if len(matches) == 1 else None

    def project(
        self, value: JsonValue, version_id: UUID | None = None, field: str | None = None
    ) -> JsonValue:
        if isinstance(value, list):
            return [self.project(item, version_id, field) for item in value]
        if not isinstance(value, dict):
            # Old manifests can contain URL strings instead of descriptors.
            if field == "attachments" and isinstance(value, str):
                return self.project({"source_url": value}, version_id)
            return value
        result = {
            key: self.project(item, version_id, key)
            for key, item in value.items()
            if key in PUBLIC_FIELDS
        }
        attachment = self._attachment(value, version_id)
        if attachment is not None:
            result.update(
                AttachmentReference(
                    attachment_id=attachment.id,
                    sha256=attachment.sha256,
                    original_url=f"/api/v1/documents/{attachment.id}/original"
                    if attachment.storage_key and attachment.sha256
                    else None,
                ).model_dump(mode="json")
            )
        else:
            # Preserve an already-projected relative handle when DTO validation runs again.
            identifier, original = value.get("attachment_id"), value.get("original_url")
            if isinstance(identifier, str):
                try:
                    safe_path = f"/api/v1/documents/{UUID(identifier)}/original"
                except ValueError:
                    safe_path = ""
                if original is None or original == safe_path and safe_path:
                    result["original_url"] = original
        return result

    def mapping(
        self, value: dict[str, JsonValue], version_id: UUID | None = None
    ) -> dict[str, JsonValue]:
        projected = self.project(value, version_id)
        assert isinstance(projected, dict)
        return projected


async def public_provenance(session: AsyncSession, version_ids: Sequence[UUID]) -> PublicProvenance:
    attachments = list(
        await session.scalars(
            select(Attachment).where(
                Attachment.opportunity_version_id.in_(version_ids),
            )
        )
    )
    return PublicProvenance(attachments)


def project_mapping(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return PublicProvenance().mapping(value)


# Apply at every flexible response field, even on a new route that omits enrichment.
PublicJSON = Annotated[dict[str, JsonValue], BeforeValidator(project_mapping)]


def public_validation_errors(errors: list[str]) -> list[str]:
    """Stored Pydantic exception strings can contain rejected input and transport secrets."""
    grounding_messages = {
        "missing evidence",
        "evidence not on referenced page",
        "value unsupported by labeled evidence",
        "contradictory document claims",
        "negated or qualified requirement needs review",
    }
    result = []
    for error in errors:
        field, separator, message = error.partition(": ")
        if error in {
            "evidence for absent or unknown fields",
            "schema_validation_failed",
            "validation_failed",
        } or (separator and field in PUBLIC_FIELDS and message in grounding_messages):
            result.append(error)
        elif "input_value=" in error or "validation error" in error:
            result.append("schema_validation_failed")
        else:
            result.append("validation_failed")
    return result
