from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.api.company_profiles import ensure_synthetic_demo_profile
from app.models import CompanyProfile, Opportunity, OpportunityVersion
from app.ranking.eligibility import materialize_eligibility
from app.workers.jobs import _session_scope


async def evaluate_company_opportunity(
    ctx: dict[str, Any], company_profile_id: str, opportunity_version_id: str
) -> dict[str, str]:
    async with _session_scope(ctx) as session:
        row = await materialize_eligibility(
            session, UUID(company_profile_id), UUID(opportunity_version_id)
        )
        await session.commit()
        return {"status": "materialized", "eligibility_result_id": str(row.id)}


async def reconcile_eligibility_results(ctx: dict[str, Any]) -> dict[str, int]:
    """Materialize every current opportunity for every profile, including the demo."""
    async with _session_scope(ctx) as session:
        await ensure_synthetic_demo_profile(session)
        profile_ids = tuple(
            await session.scalars(select(CompanyProfile.id).order_by(CompanyProfile.id))
        )
        version_ids = tuple(
            await session.scalars(
                select(OpportunityVersion.id)
                .join(
                    Opportunity,
                    Opportunity.current_version_id == OpportunityVersion.id,
                )
                .order_by(OpportunityVersion.id)
            )
        )
        count = 0
        for profile_id in profile_ids:
            for version_id in version_ids:
                await materialize_eligibility(session, profile_id, version_id)
                count += 1
        await session.commit()
        return {"materialized": count}
