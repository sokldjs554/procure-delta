from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.delta.engine import DeltaSnapshot, compute_delta
from app.delta.rules import RULESET_VERSION
from app.extraction.base import StructuredExtractor
from app.extraction.service import (
    build_document_bundle,
    extraction_identity,
    trusted_extraction_view,
)
from app.models import (
    Attachment,
    DocumentParse,
    JobFailure,
    Opportunity,
    OpportunityDelta,
    OpportunityVersion,
    RawRecord,
    StructuredExtraction,
)


@dataclass(frozen=True)
class PreparedSnapshot:
    snapshot: DeltaSnapshot
    provenance: dict[str, Any]


async def prepare_snapshot(
    session: AsyncSession, version: OpportunityVersion, extractor: StructuredExtractor
) -> PreparedSnapshot | None:
    """Wait for known terminal inputs; expose gaps instead of treating them as absence."""
    # Refresh under the same version lock used by extraction/document writers. The
    # ORM object may have been loaded before a concurrent repair closed the gate.
    await session.refresh(version, with_for_update=True)
    if version.documents_completed_at is None:
        return None
    attachments = tuple(
        await session.scalars(
            select(Attachment)
            .where(Attachment.opportunity_version_id == version.id)
            .order_by(Attachment.source_url)
        )
    )
    gaps: list[dict[str, Any]] = []
    if version.document_gaps_json:
        gaps.append(dict(version.document_gaps_json))
    for attachment in attachments:
        if (
            attachment.download_status not in {"parsed", "unsupported", "parse_failed"}
            and not version.document_gaps_json
        ):
            return None
        if attachment.download_status != "parsed":
            gaps.append({"attachment_id": str(attachment.id), "status": attachment.download_status})
    parses = list(
        await session.scalars(
            select(DocumentParse)
            .join(Attachment)
            .where(Attachment.opportunity_version_id == version.id)
            .order_by(DocumentParse.id)
        )
    )
    for parsed in parses:
        if parsed.status != "trusted":
            gaps.append({"parse_id": str(parsed.id), "status": parsed.status})
    document = await build_document_bundle(session, version.id)
    key = extraction_identity(document, extractor)
    view = None
    extraction_id = None
    extraction_status = "no_suitable_pages"
    if document.pages:
        extraction = await session.scalar(
            select(StructuredExtraction).where(
                StructuredExtraction.opportunity_version_id == version.id,
                StructuredExtraction.extraction_key == key,
            )
        )
        if extraction is None:
            # Only terminal failure for this exact extraction input releases the gate.
            from app.workers.jobs import MAX_ATTEMPTS, job_key

            stable_key = job_key(
                "extract_version", "attachment", {"version_id": str(version.id), "key": key}
            )
            failure = await session.scalar(
                select(JobFailure).where(
                    JobFailure.job_type == "extract_version", JobFailure.job_key == stable_key
                )
            )
            if failure is None or not (failure.dead_lettered or failure.attempts >= MAX_ATTEMPTS):
                return None
            extraction_status = "dead_lettered"
            gaps.append({"stage": "extraction", "job_key": stable_key, "status": extraction_status})
        else:
            if extraction.validation_status not in {"validated", "rejected"}:
                return None
            extraction_id = str(extraction.id)
            extraction_status = extraction.validation_status
            view = await trusted_extraction_view(session, extraction.id)
            if view is None:
                gaps.append(
                    {"stage": "extraction", "extraction_id": extraction_id, "status": "untrusted"}
                )
            elif view.conflicts:
                gaps.append(
                    {
                        "stage": "extraction",
                        "extraction_id": extraction_id,
                        "status": "conflicting_claims",
                        "fields": sorted(view.conflicts),
                    }
                )
    elif attachments:
        gaps.append({"stage": "extraction", "status": "no_suitable_pages"})
    raw = await session.get_one(RawRecord, version.raw_record_id)
    return PreparedSnapshot(
        snapshot=DeltaSnapshot(
            version=version,
            raw=raw,
            attachments=attachments,
            extraction=view,
            attachment_manifest_complete=version.documents_discovered_at is not None,
        ),
        provenance={
            "version_id": str(version.id),
            "version_number": version.version_number,
            "effective_at": version.effective_at.isoformat(),
            "raw_record_id": str(raw.id),
            "normalized_sha256": version.normalized_sha256,
            "manifest_complete": version.documents_discovered_at is not None,
            "attachments": [
                {
                    "id": str(item.id),
                    "source_url": item.source_url,
                    "sha256": item.sha256,
                    "filename": item.filename,
                    "status": item.download_status,
                }
                for item in attachments
            ],
            "extraction_id": extraction_id,
            "extraction_key": key,
            "extraction_status": extraction_status,
            "gaps": gaps,
        },
    )


async def persist_delta(
    session: AsyncSession, to_version_id: UUID, extractor: StructuredExtractor
) -> tuple[str, OpportunityDelta | None]:
    target = await session.get(OpportunityVersion, to_version_id)
    if target is None:
        return "missing", None
    # Same serialization point as normalization; compute after the transition facts are committed.
    await session.scalar(
        select(Opportunity).where(Opportunity.id == target.opportunity_id).with_for_update()
    )
    if target.transition_kind == "initial":
        return "initial", None
    if target.transition_kind == "current":
        before_id = target.previous_current_version_id
        kind = "current_transition"
    else:
        before_id = await session.scalar(
            select(OpportunityVersion.id)
            .where(
                OpportunityVersion.opportunity_id == target.opportunity_id,
                OpportunityVersion.version_number < target.version_number,
            )
            .order_by(OpportunityVersion.version_number.desc())
            .limit(1)
        )
        kind = "historical" if target.transition_kind == "historical" else "legacy_unknown"
    if before_id is None:
        return "no_predecessor", None
    before_version = await session.get_one(OpportunityVersion, before_id)
    before = await prepare_snapshot(session, before_version, extractor)
    after = await prepare_snapshot(session, target, extractor)
    if before is None or after is None:
        return "pending", None
    provenance = {
        "before": before.provenance,
        "after": after.provenance,
        "ordering": "observation",
        "comparison_kind": kind,
        "transition_at": target.transition_at.isoformat() if target.transition_at else None,
    }
    result = compute_delta(before.snapshot, after.snapshot)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "inputs": provenance,
                "fields": result.field_changes_json,
                "documents": result.document_changes_json,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    existing = await session.scalar(
        select(OpportunityDelta).where(
            OpportunityDelta.from_version_id == before_id,
            OpportunityDelta.to_version_id == target.id,
            OpportunityDelta.ruleset_version == RULESET_VERSION,
            OpportunityDelta.input_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return "existing", existing
    result.ruleset_version = RULESET_VERSION
    result.input_fingerprint = fingerprint
    result.input_provenance_json = provenance
    result.comparison_kind = kind
    observed_at = await session.scalar(select(func.clock_timestamp()))
    if observed_at is None:
        raise RuntimeError("database did not provide delta finalization timestamp")
    result.created_at = observed_at
    session.add(result)
    await session.flush()
    return "created", result


async def latest_applicable_deltas(
    session: AsyncSession, opportunity_id: UUID
) -> list[OpportunityDelta]:
    """Current transition only, latest finalized revision under this ruleset.

    Historical, unknown legacy and superseded current targets are never notification inputs.
    Consumers dedupe semantic change (pair + rule codes + before/after), not revision ID.
    """
    row = await session.scalar(
        select(OpportunityDelta)
        .join(Opportunity, Opportunity.id == OpportunityDelta.opportunity_id)
        .where(
            Opportunity.id == opportunity_id,
            OpportunityDelta.to_version_id == Opportunity.current_version_id,
            OpportunityDelta.comparison_kind == "current_transition",
            OpportunityDelta.ruleset_version == RULESET_VERSION,
        )
        .order_by(OpportunityDelta.created_at.desc(), OpportunityDelta.id.desc())
        .limit(1)
    )
    return [row] if row is not None else []
