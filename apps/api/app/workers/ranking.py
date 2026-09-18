from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.api.company_profiles import ensure_synthetic_demo_profile
from app.models import CompanyProfile, Opportunity, OpportunityVersion
from app.ranking.eligibility import materialize_eligibility
from app.ranking.ranker import materialize_ranking
from app.workers.jobs import _session_scope


async def rank_company_opportunity(
    ctx: dict[str, Any], eligibility_result_id: str, as_of: str | None = None
) -> dict[str, str]:
    decision_time = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
    async with _session_scope(ctx) as session:
        eligibility_id = UUID(eligibility_result_id)
        epoch = (
            f"exact:{decision_time.isoformat()}"
            if as_of
            else f"daily:{decision_time.astimezone(UTC).date().isoformat()}"
        )
        row = await materialize_ranking(
            session, eligibility_id, as_of=decision_time, evaluation_epoch=epoch
        )
        await session.commit()
        return {"status": "materialized", "ranking_result_id": str(row.id)}


async def reconcile_ranking_results(ctx: dict[str, Any]) -> dict[str, int]:
    supplied_as_of = ctx.get("ranking_as_of")
    supplied_now = ctx.get("ranking_now")
    as_of = supplied_as_of or supplied_now or datetime.now(UTC)
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise ValueError("ranking_as_of must be a timezone-aware datetime")
    async with _session_scope(ctx) as session:
        await ensure_synthetic_demo_profile(session)
        profile_ids = tuple(await session.scalars(select(CompanyProfile.id)))
        version_ids = tuple(
            await session.scalars(
                select(OpportunityVersion.id)
                .join(Opportunity, Opportunity.current_version_id == OpportunityVersion.id)
                .where(OpportunityVersion.effective_at <= as_of)
            )
        )
        recommended = 0
        for profile_id in profile_ids:
            for version_id in version_ids:
                eligibility = await materialize_eligibility(session, profile_id, version_id)
                epoch = (
                    f"exact:{as_of.isoformat()}"
                    if supplied_as_of is not None
                    else f"daily:{as_of.astimezone(UTC).date().isoformat()}"
                )
                result = await materialize_ranking(
                    session, eligibility.id, as_of=as_of, evaluation_epoch=epoch
                )
                recommended += int(result.recommended)
        await session.commit()
        return {
            "materialized": len(profile_ids) * len(version_ids),
            "recommended": recommended,
        }
