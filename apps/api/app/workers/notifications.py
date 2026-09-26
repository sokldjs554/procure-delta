from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from arq.connections import ArqRedis
from redis.exceptions import RedisError
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import JobFailure, NotificationEvent, Watchlist
from app.notifications.base import DeliveryResult, UnconfiguredChannel
from app.notifications.email import EmailChannel, SmtpTransport
from app.notifications.local_sink import LocalSink
from app.notifications.preferences import get_preferences
from app.notifications.webhook import WebhookChannel
from app.workers.jobs import MAX_ATTEMPTS, WORKER_QUEUE, _session_scope

LEASE_SECONDS = 60


def _now(ctx: dict[str, Any]) -> datetime:
    value = ctx.get("notification_now") or datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("notification_now must be timezone-aware")
    return value


async def _finish(
    session: AsyncSession, event: NotificationEvent, result: DeliveryResult, now: datetime
) -> None:
    event.lease_token = None
    event.next_attempt_at = None
    if result.success:
        event.status = "sent"
        event.sent_at = now
        await session.execute(
            update(JobFailure)
            .where(
                JobFailure.job_type == "deliver_notification",
                JobFailure.job_key == event.dedupe_key,
            )
            .values(attempts=0, dead_lettered=False, next_retry_at=None)
        )
        return
    terminal = not result.retryable or event.attempt_count >= MAX_ATTEMPTS
    event.status = "dead_lettered" if terminal else "pending"
    if not terminal:
        event.next_attempt_at = now + timedelta(
            seconds=2**event.attempt_count + random.uniform(0, 1)
        )
    # Adapter messages/payloads are never persisted in operator-facing errors.
    safe_code = (
        result.error_code
        if result.error_code
        in {
            "channel_not_configured",
            "delivery_failed",
            "transport_error",
            "unsafe_destination",
            "attempts_exhausted",
            "http_429",
            "http_503",
            "http_4xx",
            "http_5xx",
            "http_redirect",
            "smtp_auth",
            "smtp_rejected",
            "smtp_4xx",
            "smtp_5xx",
        }
        else "delivery_failed"
    )
    values = dict(
        attempts=event.attempt_count,
        error_class="NotificationDeliveryError",
        error_message=safe_code,
        last_error_at=now,
        payload_json={"notification_event_id": str(event.id)},
        dead_lettered=terminal,
        next_retry_at=event.next_attempt_at,
    )
    await session.execute(
        insert(JobFailure)
        .values(job_type="deliver_notification", job_key=event.dedupe_key, **values)
        .on_conflict_do_update(constraint="uq_job_failure_type_key", set_=values)
    )


async def deliver_notification(ctx: dict[str, Any], notification_event_id: str) -> dict[str, str]:
    event_id, now = UUID(notification_event_id), _now(ctx)
    async with _session_scope(ctx) as session:
        event = await session.scalar(
            select(NotificationEvent)
            .where(NotificationEvent.id == event_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if event is None:
            return {"status": "missing"}
        if event.status in {"sent", "dead_lettered", "cancelled"}:
            return {"status": event.status}
        if event.next_attempt_at is not None and event.next_attempt_at > now:
            return {"status": "not_due"}
        preferences = await get_preferences(session, event.user_id)
        unwatched = (
            event.template_key != "new_high_relevance"
            and await session.scalar(
                select(Watchlist.id).where(
                    Watchlist.user_id == event.user_id,
                    Watchlist.opportunity_id == event.opportunity_id,
                )
            )
            is None
        )
        if not preferences.allows(event.channel, event.template_key) or unwatched:
            event.status = "cancelled"
            event.next_attempt_at = None
            event.lease_token = None
            await session.commit()
            return {"status": "cancelled"}
        if event.attempt_count >= MAX_ATTEMPTS:
            await _finish(
                session, event, DeliveryResult(False, error_code="attempts_exhausted"), now
            )
            await session.commit()
            return {"status": "dead_lettered"}
        event.attempt_count += 1
        token = uuid4()
        event.lease_token = token
        event.status = "sending"
        event.next_attempt_at = now + timedelta(seconds=LEASE_SECONDS)
        if event.channel == "local":
            result = await LocalSink(session).send(event)
            await _finish(session, event, result, now)
            await session.commit()
            return {"status": event.status}
        await session.commit()  # Reserve budget durably BEFORE any external side effect.
        settings = ctx.get("notification_settings") or get_settings()
        channel = ctx.get("notification_channels", {}).get(event.channel)
        if channel is None:
            destination = settings.notification_webhook_destinations.get(event.user_id)
            recipient = settings.notification_email_recipients.get(event.user_id)
            if (
                event.channel == "webhook"
                and settings.notification_external_enabled
                and destination
            ):
                channel = WebhookChannel(
                    destination.get_secret_value(),
                    payload_format=settings.notification_webhook_formats.get(
                        event.user_id, "generic"
                    ),
                )
            elif (
                event.channel == "email"
                and settings.notification_external_enabled
                and settings.notification_smtp_host
                and settings.notification_email_sender
                and recipient
            ):
                channel = EmailChannel(
                    SmtpTransport(
                        host=settings.notification_smtp_host,
                        port=settings.notification_smtp_port,
                        username=(
                            settings.notification_smtp_username.get_secret_value()
                            if settings.notification_smtp_username
                            else None
                        ),
                        password=(
                            settings.notification_smtp_password.get_secret_value()
                            if settings.notification_smtp_password
                            else None
                        ),
                        starttls=settings.notification_smtp_starttls,
                    ),
                    sender=settings.notification_email_sender,
                    recipient=recipient.get_secret_value(),
                )
            else:
                channel = UnconfiguredChannel()
        try:
            async with asyncio.timeout(20):
                result = await channel.send(event)
        except (OSError, TimeoutError):
            result = DeliveryResult(False, retryable=True, error_code="transport_error")
        except Exception:
            result = DeliveryResult(False)
        # Cancellation leaves a bounded lease. Recovery does not reset the spent attempt.
        current = await session.scalar(
            select(NotificationEvent)
            .where(NotificationEvent.id == event_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert current is not None
        if current.lease_token != token:
            return {"status": "lease_lost"}
        await _finish(session, current, result, _now(ctx))
        await session.commit()
        return {"status": current.status}


async def reconcile_notifications(ctx: dict[str, Any]) -> dict[str, int]:
    from app.notifications.triggers import reconcile_current

    if ctx.get("ranking_as_of") is not None:
        return {"processed": 0}
    async with _session_scope(ctx) as session:
        processed = await reconcile_current(session, _now(ctx))
        await session.commit()
    return {"processed": processed}


async def dispatch_pending_notifications(ctx: dict[str, Any]) -> dict[str, int]:
    """Publish a bounded page of committed outbox rows; Redis loss cannot lose the intent."""
    redis = ctx.get("redis")
    if not isinstance(redis, ArqRedis):
        return {"queued": 0}
    async with _session_scope(ctx) as session:
        rows = list(
            await session.scalars(
                select(NotificationEvent)
                .where(
                    NotificationEvent.status.in_(["pending", "sending"]),
                    or_(
                        NotificationEvent.next_attempt_at.is_(None),
                        NotificationEvent.next_attempt_at <= _now(ctx),
                    ),
                )
                .order_by(
                    NotificationEvent.next_attempt_at.asc().nullsfirst(), NotificationEvent.id
                )
                .limit(100)
            )
        )
        pending = [(str(row.id), row.attempt_count) for row in rows]
    queued = 0
    for event_id, attempt in pending:
        try:
            job = await redis.enqueue_job(
                "deliver_notification",
                event_id,
                _job_id=f"notification:{event_id}:{attempt}",
                _queue_name=WORKER_QUEUE,
            )
        except RedisError:
            break
        queued += int(job is not None)
    return {"queued": queued}
