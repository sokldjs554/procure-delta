from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy import func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Owner, Session
from app.api.evidence import documents_for, extraction_for
from app.api.provenance import public_provenance
from app.api.schemas import (
    Delta,
    DeltaHistory,
    Eligibility,
    Extraction,
    Link,
    OpportunityDetail,
    OpportunityPage,
    OpportunitySummary,
    Ranking,
    Timeline,
    Version,
)
from app.config import get_settings
from app.delta.service import latest_applicable_deltas, persist_delta, prepare_snapshot
from app.extraction.hosted import configured_extractor
from app.models import (
    CompanyProfile,
    LifecycleLink,
    Opportunity,
    OpportunityDelta,
    OpportunityVersion,
    Watchlist,
)
from app.ranking.eligibility import materialize_eligibility
from app.ranking.ranker import materialize_ranking

router = APIRouter(prefix="/api/v1", tags=["opportunities"])
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


async def owned_profile(session: AsyncSession, owner: str) -> CompanyProfile | None:
    return (
        await session.scalars(select(CompanyProfile).where(CompanyProfile.owner_user_id == owner))
    ).one_or_none()


async def get_opportunity(session: AsyncSession, identifier: UUID) -> Opportunity:
    row = await session.scalar(
        select(Opportunity)
        .where(Opportunity.id == identifier)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "Opportunity not found")
    return row


async def summarize(
    session: AsyncSession,
    row: Opportunity,
    owner: str,
    profile: CompanyProfile | None,
) -> OpportunitySummary:
    result = OpportunitySummary.model_validate(row)
    result.watched = (
        await session.scalar(
            select(Watchlist.id).where(
                Watchlist.user_id == owner,
                Watchlist.opportunity_id == row.id,
            )
        )
        is not None
    )
    result.changed_at = await session.scalar(
        select(func.max(OpportunityVersion.transition_at)).where(
            OpportunityVersion.opportunity_id == row.id,
            OpportunityVersion.transition_kind == "current",
        )
    )
    if row.current_version_id is None:
        result.decision_status = "missing_version"
    if profile is not None and row.current_version_id is not None:
        version = await session.get_one(OpportunityVersion, row.current_version_id)
        if version.documents_completed_at is None:
            result.decision_status = "documents_pending"
            return result
        now = datetime.now(UTC)
        if version.effective_at > now:
            result.decision_status = "future_version"
            return result
        result.decision_status = "ready"
        eligibility = await materialize_eligibility(session, profile.id, row.current_version_id)
        result.eligibility = Eligibility(
            id=eligibility.id,
            eligible=eligibility.eligible,
            hard_failures=eligibility.hard_fail_reasons_json.get("items", []),
            warnings=eligibility.warnings_json.get("items", []),
            ruleset_version=eligibility.ruleset_version,
        )
        if version.effective_at <= now:
            # Eligibility was just materialized from this profile/version in this
            # transaction, so ranking can reuse that verified snapshot instead of
            # rebuilding document/extraction provenance a second time.
            ranking = await materialize_ranking(
                session,
                eligibility.id,
                as_of=now,
                require_current=False,
                evaluation_epoch=f"daily:{now.date().isoformat()}",
            )
            result.ranking = Ranking(
                id=ranking.id,
                recommended=ranking.recommended,
                final_score=ranking.final_score,
                features=ranking.feature_breakdown_json,
                explanation=ranking.explanation_json,
                as_of=ranking.as_of,
                evaluation_epoch=ranking.evaluation_epoch,
                ranking_version=ranking.ranking_version,
            )
    return result


def encode_cursor(row: Opportunity, fingerprint: str) -> str:
    value = [(row.published_at or EPOCH).isoformat(), str(row.id), fingerprint]
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def decode_cursor(cursor: str, fingerprint: str) -> tuple[datetime, UUID]:
    try:
        value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (
            not isinstance(value, list)
            or len(value) != 3
            or not all(isinstance(item, str) for item in value)
            or value[2] != fingerprint
        ):
            raise ValueError
        date = datetime.fromisoformat(value[0])
        if date.tzinfo is None:
            raise ValueError
        return date, UUID(value[1])
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, "Invalid cursor for these filters") from exc


@router.get("/opportunities", response_model=OpportunityPage)
async def list_opportunities(
    session: Session,
    owner: Owner,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    lifecycle_stage: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
    buyer: Annotated[str | None, Query(max_length=255)] = None,
    status: Annotated[str | None, Query(max_length=50)] = None,
    amount_min: Annotated[Decimal | None, Query(ge=0)] = None,
    amount_max: Annotated[Decimal | None, Query(ge=0)] = None,
    deadline_from: AwareDatetime | None = None,
    deadline_to: AwareDatetime | None = None,
    eligible_only: bool = False,
    changed_since: AwareDatetime | None = None,
) -> OpportunityPage:
    if amount_min is not None and amount_max is not None and amount_min > amount_max:
        raise HTTPException(422, "Invalid amount range")
    if deadline_from is not None and deadline_to is not None and deadline_from > deadline_to:
        raise HTTPException(422, "Invalid deadline range")
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                owner,
                q,
                lifecycle_stage,
                category,
                buyer,
                status,
                amount_min,
                amount_max,
                deadline_from,
                deadline_to,
                eligible_only,
                changed_since,
            ],
            default=str,
        ).encode()
    ).hexdigest()
    published = func.coalesce(Opportunity.published_at, EPOCH)
    statement = select(Opportunity)
    for column, value in [
        (Opportunity.lifecycle_stage, lifecycle_stage),
        (Opportunity.procurement_type, category),
        (Opportunity.status, status),
    ]:
        if value is not None:
            statement = statement.where(column == value)
    if buyer:
        statement = statement.where(Opportunity.buyer_name.contains(buyer, autoescape=True))
    if q:
        statement = statement.where(
            or_(
                Opportunity.title.icontains(q, autoescape=True),
                Opportunity.buyer_name.icontains(q, autoescape=True),
            )
        )
    for range_column, lower, upper in [
        (Opportunity.estimated_amount, amount_min, amount_max),
        (Opportunity.closes_at, deadline_from, deadline_to),
    ]:
        if lower is not None:
            statement = statement.where(range_column >= lower)
        if upper is not None:
            statement = statement.where(range_column <= upper)
    if changed_since is not None:
        statement = statement.where(
            select(OpportunityVersion.id)
            .where(
                OpportunityVersion.opportunity_id == Opportunity.id,
                OpportunityVersion.transition_kind == "current",
                OpportunityVersion.transition_at > changed_since,
            )
            .exists()
        )
    if cursor:
        date, identifier = decode_cursor(cursor, fingerprint)
        statement = statement.where(
            tuple_(published, Opportunity.id) < tuple_(literal(date), literal(identifier))
        )
    statement = statement.order_by(published.desc(), Opportunity.id.desc())
    profile = await owned_profile(session, owner)
    items: list[OpportunitySummary] = []
    selected: list[Opportunity] = []
    next_cursor = None
    # Filtering uses current materialized identities, never stale retained eligibility rows.
    # Scan bounded batches; continuation can be present on a short eligible-only page.
    for batch in range(10):
        rows = list(await session.scalars(statement.limit(100 if eligible_only else limit + 1)))
        for row in rows:
            item = await summarize(session, row, owner, profile)
            if eligible_only and (
                item.eligibility is None
                or not item.eligibility.eligible
                or item.eligibility.warnings
            ):
                continue
            if len(items) == limit:
                next_cursor = encode_cursor(selected[-1], fingerprint)
                break
            items.append(item)
            selected.append(row)
        if next_cursor or not eligible_only or len(rows) < 100:
            break
        last = rows[-1]
        if batch == 9:
            next_cursor = encode_cursor(last, fingerprint)
        statement = statement.where(
            tuple_(published, Opportunity.id)
            < tuple_(literal(last.published_at or EPOCH), literal(last.id))
        )
    await session.commit()
    return OpportunityPage(items=items, next_cursor=next_cursor)


async def timeline_for(session: AsyncSession, identifier: UUID) -> Timeline:
    # Traverse only accepted active edges; retracted decisions never expand the current chain.
    visited = {identifier}
    active: dict[UUID, LifecycleLink] = {}
    frontier = {identifier}
    while frontier:
        links = list(
            await session.scalars(
                select(LifecycleLink).where(
                    LifecycleLink.status == "active",
                    or_(
                        LifecycleLink.parent_opportunity_id.in_(frontier),
                        LifecycleLink.child_opportunity_id.in_(frontier),
                    ),
                )
            )
        )
        neighbors = {
            node
            for link in links
            for node in (link.parent_opportunity_id, link.child_opportunity_id)
        }
        active.update({link.id: link for link in links})
        frontier = neighbors - visited
        visited.update(frontier)
        if len(visited) > 1000:
            raise HTTPException(409, "Lifecycle component exceeds display limit")
    historical = await session.scalars(
        select(LifecycleLink)
        .where(
            LifecycleLink.status != "active",
            or_(
                LifecycleLink.parent_opportunity_id.in_(visited),
                LifecycleLink.child_opportunity_id.in_(visited),
            ),
        )
        .order_by(LifecycleLink.created_at, LifecycleLink.id)
    )
    return Timeline(
        opportunity_ids=sorted(visited),
        active_links=[
            Link.model_validate(link)
            for link in sorted(active.values(), key=lambda row: (row.created_at, row.id))
        ],
        historical_links=[Link.model_validate(link) for link in historical],
    )


async def delta_history(session: AsyncSession, row: Opportunity) -> DeltaHistory:
    ready = False
    if row.current_version_id:
        version = await session.get_one(OpportunityVersion, row.current_version_id)
        extractor = configured_extractor(get_settings())
        ready = await prepare_snapshot(session, version, extractor) is not None
        if ready and version.previous_current_version_id:
            before = await session.get_one(OpportunityVersion, version.previous_current_version_id)
            ready = await prepare_snapshot(session, before, extractor) is not None
        if ready:
            # Reuse/materialize the exact current input fingerprint before selecting history.
            await persist_delta(session, version.id, extractor)
    applicable = (
        {item.id for item in await latest_applicable_deltas(session, row.id)} if ready else set()
    )
    rows = list(
        await session.scalars(
            select(OpportunityDelta)
            .where(
                OpportunityDelta.opportunity_id == row.id,
            )
            .order_by(OpportunityDelta.created_at.desc(), OpportunityDelta.id.desc())
        )
    )
    projection = await public_provenance(
        session,
        list(
            {
                identifier
                for item in rows
                for identifier in (item.from_version_id, item.to_version_id)
            }
        ),
    )
    items = [
        Delta.model_validate(
            {
                **{
                    name: getattr(item, name)
                    for name in Delta.model_fields
                    if name != "applicable_now"
                },
                "applicable_now": item.id in applicable,
                "document_changes_json": projection.mapping(item.document_changes_json),
                "field_changes_json": projection.mapping(item.field_changes_json),
            }
        )
        for item in rows
    ]
    return DeltaHistory(items=items, current_inputs_ready=ready)


@router.get("/opportunities/{identifier}", response_model=OpportunityDetail)
async def detail(identifier: UUID, session: Session, owner: Owner) -> OpportunityDetail:
    row = await get_opportunity(session, identifier)
    summary = await summarize(session, row, owner, await owned_profile(session, owner))
    versions = list(
        await session.scalars(
            select(OpportunityVersion)
            .where(
                OpportunityVersion.opportunity_id == identifier,
            )
            .order_by(OpportunityVersion.version_number.desc())
        )
    )
    projection = await public_provenance(session, [v.id for v in versions])
    public_versions = [
        Version.model_validate(
            {
                **{name: getattr(v, name) for name in Version.model_fields},
                "normalized_json": projection.mapping(v.normalized_json, v.id),
            }
        )
        for v in versions
    ]
    result = OpportunityDetail(
        **summary.model_dump(),
        versions=public_versions,
        timeline=await timeline_for(session, identifier),
        deltas=await delta_history(session, row),
        documents=await documents_for(session, row.current_version_id)
        if row.current_version_id
        else [],
        extraction=await extraction_for(session, row.current_version_id)
        if row.current_version_id
        else Extraction(status="missing_version"),
    )
    await session.commit()
    return result


@router.get("/opportunities/{identifier}/timeline", response_model=Timeline)
async def timeline(identifier: UUID, session: Session, owner: Owner) -> Timeline:
    await get_opportunity(session, identifier)
    return await timeline_for(session, identifier)


@router.get("/opportunities/{identifier}/deltas", response_model=DeltaHistory)
async def deltas(identifier: UUID, session: Session, owner: Owner) -> DeltaHistory:
    result = await delta_history(session, await get_opportunity(session, identifier))
    await session.commit()
    return result


@router.get("/opportunities/{identifier}/eligibility", response_model=Eligibility | None)
async def eligibility(identifier: UUID, session: Session, owner: Owner) -> Eligibility | None:
    row = await get_opportunity(session, identifier)
    result = await summarize(session, row, owner, await owned_profile(session, owner))
    await session.commit()
    return result.eligibility


@router.get("/opportunities/{identifier}/ranking", response_model=Ranking | None)
async def ranking(identifier: UUID, session: Session, owner: Owner) -> Ranking | None:
    row = await get_opportunity(session, identifier)
    result = await summarize(session, row, owner, await owned_profile(session, owner))
    await session.commit()
    return result.ranking
