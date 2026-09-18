from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LocalNotificationReceipt, NotificationEvent
from app.notifications.base import DeliveryResult


class LocalSink:
    """Receipt and event completion must commit together in the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def send(self, event: NotificationEvent) -> DeliveryResult:
        await self.session.execute(
            insert(LocalNotificationReceipt)
            .values(notification_event_id=event.id, payload_json=event.payload_json)
            .on_conflict_do_nothing(index_elements=["notification_event_id"])
        )
        return DeliveryResult(success=True)
