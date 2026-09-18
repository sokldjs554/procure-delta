from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.lifecycle.linker import GRAPH_LOCK_ID
from app.models import LifecycleLink, Opportunity, OpportunityVersion, RawRecord
from app.services.normalize import NormalizedOpportunityInput


@dataclass(frozen=True, slots=True)
class VersioningOutcome:
    created: bool
    opportunity_id: UUID
    version_id: UUID
    version_number: int


def _apply_current(opportunity: Opportunity, value: NormalizedOpportunityInput) -> None:
    opportunity.title = value.title
    opportunity.buyer_name = value.buyer_name
    opportunity.procurement_type = value.procurement_type
    opportunity.lifecycle_stage = value.lifecycle_stage
    opportunity.estimated_amount = value.estimated_amount
    opportunity.currency = value.currency
    opportunity.published_at = value.published_at
    opportunity.closes_at = value.closes_at
    opportunity.status = value.status


async def upsert_opportunity_version(
    session: AsyncSession,
    raw: RawRecord,
    normalized: NormalizedOpportunityInput,
) -> VersioningOutcome:
    """Persist one normalized state under a database-serialized canonical key."""
    if raw.id is None:
        raise ValueError("raw record must be persisted before normalization")
    if raw.source_id != normalized.source_id or raw.source_record_id != normalized.source_record_id:
        raise ValueError("normalized source identity must match the immutable raw identity")

    # Keep the global graph lock first in the lock order used by normalization and linking.
    await session.execute(select(func.pg_advisory_xact_lock(GRAPH_LOCK_ID)))
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:canonical_key, 0))"),
        {"canonical_key": normalized.canonical_key},
    )
    await session.refresh(raw, attribute_names=["normalization_status", "normalized_version_id"])
    if raw.normalized_version_id is not None:
        processed = await session.get_one(OpportunityVersion, raw.normalized_version_id)
        raw.normalization_status = "normalized"
        raw.normalized_at = datetime.now(UTC)
        return VersioningOutcome(
            created=False,
            opportunity_id=processed.opportunity_id,
            version_id=processed.id,
            version_number=processed.version_number,
        )
    opportunity = await session.scalar(
        select(Opportunity)
        .where(Opportunity.canonical_key == normalized.canonical_key)
        .with_for_update()
    )
    if opportunity is None:
        opportunity = Opportunity(
            canonical_key=normalized.canonical_key,
            title=normalized.title,
            buyer_name=normalized.buyer_name,
        )
        _apply_current(opportunity, normalized)
        opportunity.current_effective_at = normalized.effective_at
        session.add(opportunity)
        await session.flush()

    existing = (
        await session.get(OpportunityVersion, opportunity.current_version_id)
        if opportunity.current_version_id is not None
        else None
    )
    if existing is not None and existing.normalized_sha256 != normalized.normalized_sha256:
        existing = None
    if existing is not None:
        if (
            opportunity.current_effective_at is None
            or normalized.effective_at > opportunity.current_effective_at
        ):
            opportunity.current_effective_at = normalized.effective_at
        raw.normalization_status = "normalized"
        raw.normalized_at = datetime.now(UTC)
        raw.normalized_version_id = existing.id
        return VersioningOutcome(
            created=False,
            opportunity_id=opportunity.id,
            version_id=existing.id,
            version_number=existing.version_number,
        )

    latest_version_number = await session.scalar(
        select(func.max(OpportunityVersion.version_number)).where(
            OpportunityVersion.opportunity_id == opportunity.id
        )
    )
    next_version = (latest_version_number or 0) + 1
    becomes_current = (
        opportunity.current_effective_at is None
        or normalized.effective_at >= opportunity.current_effective_at
    )
    decision_at = await session.scalar(select(func.clock_timestamp()))
    version = OpportunityVersion(
        opportunity_id=opportunity.id,
        version_number=next_version,
        raw_record_id=raw.id,
        source_record_id=raw.source_record_id,
        effective_at=normalized.effective_at,
        normalized_json=normalized.normalized_json,
        normalized_sha256=normalized.normalized_sha256,
        extraction_version="normalizer-v1",
        previous_current_version_id=opportunity.current_version_id,
        transition_kind=("initial" if opportunity.current_version_id is None else "current")
        if becomes_current
        else "historical",
        transition_at=decision_at,
    )
    session.add(version)
    await session.flush()

    if becomes_current:
        if opportunity.current_version_id is not None:
            observed_at = await session.scalar(select(func.clock_timestamp()))
            if observed_at is None:
                raise RuntimeError("database did not provide a lifecycle observation timestamp")
            await session.execute(
                update(LifecycleLink)
                .where(
                    LifecycleLink.status == "active",
                    or_(
                        LifecycleLink.parent_opportunity_id == opportunity.id,
                        LifecycleLink.child_opportunity_id == opportunity.id,
                    ),
                )
                .values(status="retracted", retracted_at=observed_at)
            )
        opportunity.current_version_id = version.id
        opportunity.current_effective_at = normalized.effective_at
        _apply_current(opportunity, normalized)
    raw.normalization_status = "normalized"
    raw.normalized_at = datetime.now(UTC)
    raw.normalized_version_id = version.id
    await session.flush()
    return VersioningOutcome(
        created=True,
        opportunity_id=opportunity.id,
        version_id=version.id,
        version_number=next_version,
    )
