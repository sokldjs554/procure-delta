from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.api.auth import Owner, Session
from app.api.opportunities import get_opportunity, owned_profile, summarize
from app.api.schemas import OpportunityPage, WatchState
from app.models import Opportunity, Watchlist

router = APIRouter(prefix="/api/v1", tags=["watchlist"])


@router.post("/opportunities/{identifier}/watch", response_model=WatchState)
async def watch(identifier: UUID, session: Session, owner: Owner) -> WatchState:
    await get_opportunity(session, identifier)
    await session.execute(
        insert(Watchlist)
        .values(user_id=owner, opportunity_id=identifier)
        .on_conflict_do_nothing(constraint="uq_watchlist_user_opportunity")
    )
    await session.commit()
    return WatchState(opportunity_id=identifier)


@router.delete("/opportunities/{identifier}/watch", status_code=204)
async def unwatch(identifier: UUID, session: Session, owner: Owner) -> None:
    await session.execute(
        delete(Watchlist).where(Watchlist.user_id == owner, Watchlist.opportunity_id == identifier)
    )
    await session.commit()


@router.get("/watchlist", response_model=OpportunityPage)
async def watchlist(
    session: Session,
    owner: Owner,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
) -> OpportunityPage:
    statement = select(Opportunity).join(Watchlist).where(Watchlist.user_id == owner)
    if cursor:
        statement = statement.where(Opportunity.id > cursor)
    rows = list(await session.scalars(statement.order_by(Opportunity.id).limit(limit + 1)))
    profile = await owned_profile(session, owner)
    items = [await summarize(session, row, owner, profile) for row in rows[:limit]]
    await session.commit()
    return OpportunityPage(
        items=items, next_cursor=str(rows[limit - 1].id) if len(rows) > limit else None
    )
