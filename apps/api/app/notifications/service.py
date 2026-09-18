from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationEvent


async def enqueue_notification(
    session: AsyncSession,
    *,
    user_id: str,
    opportunity_id: UUID,
    channel: str,
    template_key: str,
    semantic_identity: dict[str, Any],
    payload: dict[str, Any],
    delta_id: UUID | None = None,
) -> NotificationEvent:
    """Insert an immutable outbox event in the caller's transaction; never publish early."""
    identity = [user_id, str(opportunity_id), channel, template_key, semantic_identity]
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
    await session.execute(
        insert(NotificationEvent)
        .values(
            user_id=user_id,
            opportunity_id=opportunity_id,
            channel=channel,
            template_key=template_key,
            payload_json=payload,
            delta_id=delta_id,
            dedupe_key=key,
            status="pending",
            attempt_count=0,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    return (
        await session.scalars(select(NotificationEvent).where(NotificationEvent.dedupe_key == key))
    ).one()
