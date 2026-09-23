from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.auth import Owner, Session
from app.api.schemas import ContractProcessHistory, ContractProcessSnapshotSummary
from app.models import ContractProcessSnapshot, Opportunity, OpportunityVersion

router = APIRouter(prefix="/api/v1", tags=["contract-process"])


@router.get(
    "/opportunities/{identifier}/contract-process",
    response_model=ContractProcessHistory,
)
async def contract_process_history(
    identifier: UUID,
    session: Session,
    owner: Owner,
) -> ContractProcessHistory:
    del owner
    opportunity = await session.get(Opportunity, identifier)
    if opportunity is None:
        raise HTTPException(404, "Opportunity not found")
    rows = list(
        await session.scalars(
            select(ContractProcessSnapshot)
            .join(
                OpportunityVersion,
                OpportunityVersion.id == ContractProcessSnapshot.opportunity_version_id,
            )
            .where(OpportunityVersion.opportunity_id == identifier)
            .order_by(
                ContractProcessSnapshot.fetched_at.desc(),
                ContractProcessSnapshot.page_no,
                ContractProcessSnapshot.id,
            )
            .limit(100)
        )
    )
    return ContractProcessHistory(
        items=[
            ContractProcessSnapshotSummary(
                id=row.id,
                opportunity_version_id=row.opportunity_version_id,
                inquiry_div=row.inquiry_div,
                page_no=row.page_no,
                total_count=row.total_count,
                response_sha256=row.response_sha256,
                identifiers=row.identifiers_json,
                fetched_at=row.fetched_at,
            )
            for row in rows
        ]
    )
