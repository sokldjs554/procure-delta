from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.auth import Owner, Session
from app.api.provenance import public_provenance
from app.api.schemas import Notification, NotificationPage
from app.models import LocalNotificationReceipt, NotificationEvent, OpportunityVersion
from app.notifications.preferences import PreferenceValues, get_preferences, set_preferences

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/preferences", response_model=PreferenceValues)
async def preferences(session: Session, owner: Owner) -> PreferenceValues:
    return await get_preferences(session, owner)


@router.put("/preferences", response_model=PreferenceValues)
async def update_preferences(
    values: PreferenceValues, session: Session, owner: Owner
) -> PreferenceValues:
    result = await set_preferences(session, owner, values)
    await session.commit()
    return result


@router.get("", response_model=NotificationPage)
async def history(
    session: Session,
    owner: Owner,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
) -> NotificationPage:
    statement = (
        select(NotificationEvent, LocalNotificationReceipt)
        .outerjoin(
            LocalNotificationReceipt,
            LocalNotificationReceipt.notification_event_id == NotificationEvent.id,
        )
        .where(NotificationEvent.user_id == owner)
    )
    if cursor:
        statement = statement.where(NotificationEvent.id > cursor)
    rows = (await session.execute(statement.order_by(NotificationEvent.id).limit(limit + 1))).all()
    version_ids = list(
        await session.scalars(
            select(OpportunityVersion.id).where(
                OpportunityVersion.opportunity_id.in_(
                    [event.opportunity_id for event, _ in rows[:limit]]
                ),
            )
        )
    )
    projection = await public_provenance(session, version_ids)
    return NotificationPage(
        items=[
            Notification(
                id=event.id,
                opportunity_id=event.opportunity_id,
                delta_id=event.delta_id,
                channel=event.channel,
                template_key=event.template_key,
                status=event.status,
                attempt_count=event.attempt_count,
                next_attempt_at=event.next_attempt_at,
                sent_at=event.sent_at,
                payload=projection.mapping(event.payload_json),
                receipt_id=receipt.id if receipt else None,
                received_at=receipt.received_at if receipt else None,
            )
            for event, receipt in rows[:limit]
        ],
        next_cursor=str(rows[limit - 1][0].id) if len(rows) > limit else None,
    )
