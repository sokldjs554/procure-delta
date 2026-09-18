from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.delta.service import latest_applicable_deltas, persist_delta
from app.extraction.hosted import configured_extractor
from app.models import (
    CompanyProfile,
    LifecycleLink,
    Opportunity,
    OpportunityVersion,
    Watchlist,
)
from app.notifications.preferences import get_preferences
from app.notifications.service import enqueue_notification
from app.ranking.eligibility import materialize_eligibility
from app.ranking.ranker import materialize_ranking


def _semantic(value: Any) -> Any:
    """Evidence provenance may be repaired without changing the business event."""
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in value.items() if "evidence" not in key}
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    return value


async def _emit(
    session: AsyncSession,
    owner: str,
    item_id: UUID,
    trigger: str,
    identity: dict[str, Any],
    payload: dict[str, Any],
    delta_id: UUID | None = None,
) -> None:
    preferences = await get_preferences(session, owner)
    for channel in set(preferences.channels):
        if preferences.allows(channel, trigger):
            await enqueue_notification(
                session,
                user_id=owner,
                opportunity_id=item_id,
                channel=channel,
                template_key=trigger,
                semantic_identity=identity,
                payload=payload,
                delta_id=delta_id,
            )


def _observed_after_watch(version: OpportunityVersion, watch: Watchlist, now: datetime) -> bool:
    return (
        version.transition_kind in {"initial", "current"}
        and version.transition_at is not None
        and watch.created_at <= version.transition_at <= now
        and version.effective_at <= now
    )


async def reconcile_current(session: AsyncSession, now: datetime) -> int:
    """Reconcile current materializations, never retained historical ranking/delta rows."""
    items = list(
        await session.scalars(
            select(Opportunity)
            .where(Opportunity.current_version_id.is_not(None))
            .order_by(Opportunity.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    profiles = list(
        await session.scalars(
            select(CompanyProfile)
            .order_by(CompanyProfile.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    processed = 0
    for profile in profiles:
        preferences = await get_preferences(session, profile.owner_user_id)
        if not preferences.enabled or "new_high_relevance" not in preferences.triggers:
            continue
        for item in items:
            version = await session.get_one(OpportunityVersion, item.current_version_id)
            if version.effective_at > now or item.lifecycle_stage in {
                "award",
                "opening",
                "contract",
            }:
                continue
            eligibility = await materialize_eligibility(session, profile.id, version.id)
            ranking = await materialize_ranking(
                session,
                eligibility.id,
                as_of=now,
                evaluation_epoch=f"daily:{now.astimezone(UTC).date().isoformat()}",
            )
            if ranking.recommended:
                await _emit(
                    session,
                    profile.owner_user_id,
                    item.id,
                    "new_high_relevance",
                    {"canonical_key": item.canonical_key},
                    {
                        "title": item.title,
                        "version_id": str(version.id),
                        "ranking_result_id": str(ranking.id),
                        "final_score": str(ranking.final_score),
                        "explanation": ranking.explanation_json,
                    },
                )
            processed += 1
    watches = list(await session.scalars(select(Watchlist).order_by(Watchlist.id)))
    extractor = configured_extractor(get_settings())
    for item in items:
        item_watches = [watch for watch in watches if watch.opportunity_id == item.id]
        version = await session.get_one(OpportunityVersion, item.current_version_id)
        applicable = [watch for watch in item_watches if _observed_after_watch(version, watch, now)]
        if not applicable or version.transition_kind != "current":
            continue
        _, current_delta = await persist_delta(session, version.id, extractor)
        if current_delta is None:
            continue
        latest = await latest_applicable_deltas(session, item.id)
        if not latest or latest[0].id != current_delta.id:
            continue
        delta = current_delta
        fields = delta.field_changes_json
        triggers = []
        if fields or any(delta.document_changes_json.values()):
            triggers.append("watched_material_change")
        if "closes_at" in fields and delta.impact_level in {"medium", "high"}:
            triggers.append("deadline_changed")
        if set(fields) & {
            "regions",
            "required_certifications",
            "required_capabilities",
            "participation_constraints",
            "budget",
        }:
            triggers.append("eligibility_changed")
        identity = {
            "from_version_id": str(delta.from_version_id),
            "to_version_id": str(delta.to_version_id),
            "fields": _semantic(fields),
            "documents": _semantic(delta.document_changes_json),
            "impact": delta.impact_level,
            "reasons": delta.impact_reasons_json.get("codes", []),
        }
        payload = {
            "title": item.title,
            "delta_id": str(delta.id),
            "field_changes": fields,
            "document_changes": delta.document_changes_json,
            "impact_level": delta.impact_level,
            "reason_codes": delta.impact_reasons_json.get("codes", []),
            "from_version_id": str(delta.from_version_id),
            "to_version_id": str(delta.to_version_id),
        }
        for watch in applicable:
            for trigger in triggers:
                await _emit(session, watch.user_id, item.id, trigger, identity, payload, delta.id)
    await _outcomes(session, items, watches, now)
    return processed


async def _outcomes(
    session: AsyncSession, items: list[Opportunity], watches: list[Watchlist], now: datetime
) -> None:
    by_id = {item.id: item for item in items}
    links = list(
        await session.scalars(select(LifecycleLink).where(LifecycleLink.status == "active"))
    )
    # Stale active edges awaiting relinking cannot justify an outcome association.
    parents = {
        link.child_opportunity_id: link
        for link in links
        if link.parent_opportunity_id in by_id
        and link.child_opportunity_id in by_id
        and link.parent_version_id == by_id[link.parent_opportunity_id].current_version_id
        and link.child_version_id == by_id[link.child_opportunity_id].current_version_id
    }
    for outcome in items:
        if outcome.lifecycle_stage not in {"award", "opening", "contract"}:
            continue
        version = await session.get_one(OpportunityVersion, outcome.current_version_id)
        ancestor = outcome.id
        path: list[str] = []
        seen: set[UUID] = set()
        while ancestor not in seen:
            seen.add(ancestor)
            for watch in watches:
                if watch.opportunity_id != ancestor or not _observed_after_watch(
                    version, watch, now
                ):
                    continue
                await _emit(
                    session,
                    watch.user_id,
                    watch.opportunity_id,
                    "outcome_published",
                    {"outcome_id": str(outcome.id), "stage": outcome.lifecycle_stage},
                    {
                        "title": outcome.title,
                        "stage": outcome.lifecycle_stage,
                        "outcome_opportunity_id": str(outcome.id),
                        "outcome_version_id": str(version.id),
                        "watched_opportunity_id": str(watch.opportunity_id),
                        "link_ids": list(path),
                    },
                )
            link = parents.get(ancestor)
            if link is None:
                break
            path.append(str(link.id))
            ancestor = link.parent_opportunity_id
