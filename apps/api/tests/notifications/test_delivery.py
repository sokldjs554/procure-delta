from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.models import JobFailure, NotificationEvent, Opportunity


@pytest_asyncio.fixture
async def delivery_context(worker_session_factory):
    async with worker_session_factory() as session:
        item = Opportunity(canonical_key=uuid4().hex, title="Synthetic", buyer_name="Synthetic")
        session.add(item)
        await session.commit()
    ctx = {"session_factory": worker_session_factory}
    yield ctx, item.id
    import app.models as models

    async with worker_session_factory() as session:
        ids = select(NotificationEvent.id).where(NotificationEvent.opportunity_id == item.id)
        if hasattr(models, "LocalNotificationReceipt"):
            await session.execute(
                delete(models.LocalNotificationReceipt).where(
                    models.LocalNotificationReceipt.notification_event_id.in_(ids)
                )
            )
        await session.execute(
            delete(JobFailure).where(
                JobFailure.job_type == "deliver_notification",
                JobFailure.job_key.in_(
                    select(NotificationEvent.dedupe_key).where(
                        NotificationEvent.opportunity_id == item.id
                    )
                ),
            )
        )
        await session.execute(
            delete(NotificationEvent).where(NotificationEvent.opportunity_id == item.id)
        )
        await session.execute(delete(Opportunity).where(Opportunity.id == item.id))
        await session.commit()


async def enqueue(ctx, item_id, channel="local"):
    from app.notifications.preferences import PreferenceValues, set_preferences
    from app.notifications.service import enqueue_notification

    async with ctx["session_factory"]() as session:
        await set_preferences(
            session, "synthetic-notification-owner", PreferenceValues(channels=[channel])
        )
        event = await enqueue_notification(
            session,
            user_id="synthetic-notification-owner",
            opportunity_id=item_id,
            channel=channel,
            template_key="new_high_relevance",
            semantic_identity={"new": True},
            payload={"title": "Synthetic opportunity"},
        )
        await session.commit()
        return event.id


@pytest.mark.asyncio
async def test_dispatch_uses_committed_outbox_and_real_arq_delivery(delivery_context, monkeypatch):
    from arq.connections import RedisSettings, create_pool
    from arq.jobs import Job
    from arq.worker import Worker

    from app.workers.notifications import deliver_notification, dispatch_pending_notifications

    queue = "arq:notification-test:" + uuid4().hex
    monkeypatch.setattr("app.workers.notifications.WORKER_QUEUE", queue)

    ctx, item_id = delivery_context
    event_id = await enqueue(ctx, item_id)
    redis = await create_pool(RedisSettings.from_dsn(os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")))
    try:
        ctx["redis"] = redis
        result = await dispatch_pending_notifications(ctx)
        assert result["queued"] >= 1
        job = Job(f"notification:{event_id}:0", redis, _queue_name=queue)
        info = await job.info()
        assert info.function == "deliver_notification"
        assert info.args == (str(event_id),)
        async with ctx["session_factory"]() as session:
            assert (await session.get_one(NotificationEvent, event_id)).attempt_count == 0
        worker = Worker(
            [deliver_notification],
            redis_pool=redis,
            queue_name=queue,
            ctx=ctx,
            burst=True,
            handle_signals=False,
        )
        await worker.async_run()
        async with ctx["session_factory"]() as session:
            assert (await session.get_one(NotificationEvent, event_id)).status == "sent"
        await redis.delete(f"arq:result:{job.job_id}")
    finally:
        await redis.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_webhook_setting_is_owner_scoped_disabled_by_default(delivery_context, enabled):
    from app.config import Settings
    from app.workers.notifications import deliver_notification

    ctx, item_id = delivery_context
    assert Settings().notification_external_enabled is False
    ctx["notification_settings"] = Settings(
        notification_external_enabled=enabled,
        notification_webhook_destinations={"other-owner": "https://93.184.216.34/secret"},
    )
    event_id = await enqueue(ctx, item_id, "webhook")
    assert (await deliver_notification(ctx, str(event_id)))["status"] == "dead_lettered"


@pytest.mark.asyncio
async def test_configured_owner_webhook_is_selected_only_with_explicit_enable(
    delivery_context, monkeypatch
):
    from app.config import Settings
    from app.notifications.base import DeliveryResult
    from app.workers.notifications import deliver_notification

    async def send(self, event):
        return DeliveryResult(True)

    monkeypatch.setattr("app.notifications.webhook.WebhookChannel.send", send)
    ctx, item_id = delivery_context
    ctx["notification_settings"] = Settings(
        notification_external_enabled=True,
        notification_webhook_destinations={
            "synthetic-notification-owner": "https://93.184.216.34/secret"
        },
    )
    event_id = await enqueue(ctx, item_id, "webhook")
    assert (await deliver_notification(ctx, str(event_id)))["status"] == "sent"


@pytest.mark.asyncio
async def test_configured_email_delivers_over_real_local_smtp(delivery_context):
    from email import policy
    from email.parser import BytesParser

    from app.config import Settings
    from app.workers.notifications import deliver_notification

    received: list[bytes] = []

    async def smtp_session(reader, writer):
        writer.write(b"220 localhost ESMTP\r\n")
        await writer.drain()
        data_mode = False
        body = bytearray()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                if data_mode:
                    if line == b".\r\n":
                        received.append(bytes(body))
                        body.clear()
                        data_mode = False
                        writer.write(b"250 queued\r\n")
                    else:
                        body.extend(line[1:] if line.startswith(b"..") else line)
                    await writer.drain()
                    continue

                command = line.decode("utf-8", errors="replace").strip()
                verb = command.split(" ", 1)[0].upper()
                if verb in {"EHLO", "HELO"}:
                    writer.write(b"250-localhost\r\n250 HELP\r\n")
                elif verb in {"MAIL", "RCPT", "RSET", "NOOP"}:
                    writer.write(b"250 ok\r\n")
                elif verb == "DATA":
                    data_mode = True
                    writer.write(b"354 end with dot\r\n")
                elif verb == "QUIT":
                    writer.write(b"221 bye\r\n")
                    await writer.drain()
                    break
                else:
                    writer.write(b"500 unsupported\r\n")
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(smtp_session, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    ctx, item_id = delivery_context
    ctx["notification_settings"] = Settings(
        _env_file=None,
        notification_external_enabled=True,
        notification_smtp_host="127.0.0.1",
        notification_smtp_port=port,
        notification_smtp_starttls=False,
        notification_email_sender="sender@example.invalid",
        notification_email_recipients={
            "synthetic-notification-owner": "recipient@example.invalid"
        },
    )
    try:
        event_id = await enqueue(ctx, item_id, "email")
        assert (await deliver_notification(ctx, str(event_id)))["status"] == "sent"
    finally:
        server.close()
        await server.wait_closed()

    assert len(received) == 1
    message = BytesParser(policy=policy.default).parsebytes(received[0])
    assert message["From"] == "sender@example.invalid"
    assert message["To"] == "recipient@example.invalid"
    assert "Synthetic opportunity" in message.get_content()

    async with ctx["session_factory"]() as session:
        event = await session.get_one(NotificationEvent, event_id)
        assert (event.status, event.attempt_count) == ("sent", 1)
        assert message["Message-ID"] == f"<{event.dedupe_key}@procure-delta.invalid>"


@pytest.mark.asyncio
async def test_unknown_exception_never_persists_secret(delivery_context):
    from app.workers.notifications import deliver_notification

    class Broken:
        async def send(self, event):
            raise RuntimeError("recipient@example.invalid https://secret.example/token=hidden")

    ctx, item_id = delivery_context
    ctx["notification_channels"] = {"webhook": Broken()}
    event_id = await enqueue(ctx, item_id, "webhook")
    await deliver_notification(ctx, str(event_id))
    async with ctx["session_factory"]() as session:
        failure = await session.scalar(
            select(JobFailure).where(
                JobFailure.payload_json["notification_event_id"].astext == str(event_id)
            )
        )
        assert failure.error_message == "delivery_failed"
        assert "secret" not in str(failure.payload_json)


@pytest.mark.asyncio
async def test_three_crashed_attempts_dead_letter_without_fourth_send(delivery_context):
    from app.workers.notifications import deliver_notification

    ctx, item_id = delivery_context
    event_id = await enqueue(ctx, item_id, "webhook")
    async with ctx["session_factory"]() as session:
        event = await session.get_one(NotificationEvent, event_id)
        event.status, event.attempt_count = "sending", 3
        event.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert (await deliver_notification(ctx, str(event_id)))["status"] == "dead_lettered"
    async with ctx["session_factory"]() as session:
        failure = await session.scalar(
            select(JobFailure).where(
                JobFailure.payload_json["notification_event_id"].astext == str(event_id)
            )
        )
        assert failure.attempts == 3 and failure.error_message == "attempts_exhausted"


@pytest.mark.asyncio
async def test_redis_outage_preserves_pending_outbox(delivery_context, monkeypatch):
    from arq.connections import RedisSettings, create_pool
    from redis.exceptions import ConnectionError

    from app.workers.notifications import dispatch_pending_notifications

    ctx, item_id = delivery_context
    event_id = await enqueue(ctx, item_id)
    redis = await create_pool(RedisSettings.from_dsn(os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")))

    async def unavailable(*args, **kwargs):
        raise ConnectionError("synthetic outage")

    monkeypatch.setattr(redis, "enqueue_job", unavailable)
    ctx["redis"] = redis
    try:
        assert await dispatch_pending_notifications(ctx) == {"queued": 0}
        async with ctx["session_factory"]() as session:
            event = await session.get_one(NotificationEvent, event_id)
            assert (event.status, event.attempt_count) == ("pending", 0)
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_external_success_commit_failure_retries_same_receiver_idempotency_key(
    delivery_context,
):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.notifications.base import DeliveryResult
    from app.workers.notifications import deliver_notification

    class CommitFailsOnce(AsyncSession):
        commits = 0

        async def commit(self):
            type(self).commits += 1
            if type(self).commits == 2:
                raise RuntimeError("synthetic commit interruption after external success")
            await super().commit()

    received, attempts = set(), []

    class Receiver:
        async def send(self, event):
            received.add(event.dedupe_key)
            attempts.append(event.dedupe_key)
            return DeliveryResult(True)

    ctx, item_id = delivery_context
    event_id = await enqueue(ctx, item_id, "webhook")
    original_factory = ctx["session_factory"]
    ctx["session_factory"] = async_sessionmaker(
        original_factory.kw["bind"], class_=CommitFailsOnce, expire_on_commit=False
    )
    ctx["notification_channels"] = {"webhook": Receiver()}
    with pytest.raises(RuntimeError, match="synthetic commit"):
        await deliver_notification(ctx, str(event_id))
    ctx["session_factory"] = original_factory
    async with original_factory() as session:
        event = await session.get_one(NotificationEvent, event_id)
        assert event.status == "sending" and event.attempt_count == 1
        ctx["notification_now"] = event.next_attempt_at + timedelta(seconds=1)
    assert (await deliver_notification(ctx, str(event_id)))["status"] == "sent"
    assert len(attempts) == 2 and len(received) == 1


@pytest.mark.asyncio
async def test_local_receipt_rolls_back_with_failed_completion_commit(delivery_context):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.models import LocalNotificationReceipt
    from app.workers.notifications import deliver_notification

    class CommitFails(AsyncSession):
        async def commit(self):
            raise RuntimeError("synthetic local commit interruption")

    ctx, item_id = delivery_context
    event_id = await enqueue(ctx, item_id)
    original_factory = ctx["session_factory"]
    ctx["session_factory"] = async_sessionmaker(
        original_factory.kw["bind"], class_=CommitFails, expire_on_commit=False
    )
    with pytest.raises(RuntimeError, match="synthetic local"):
        await deliver_notification(ctx, str(event_id))
    ctx["session_factory"] = original_factory
    async with original_factory() as session:
        assert (await session.get_one(NotificationEvent, event_id)).status == "pending"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(LocalNotificationReceipt)
                .where(LocalNotificationReceipt.notification_event_id == event_id)
            )
            == 0
        )
    assert (await deliver_notification(ctx, str(event_id)))["status"] == "sent"


@pytest.mark.asyncio
async def test_late_external_result_cannot_overwrite_recovered_delivery(delivery_context):
    from app.notifications.base import DeliveryResult
    from app.workers.notifications import deliver_notification

    entered, release = asyncio.Event(), asyncio.Event()

    class Receiver:
        calls = 0

        async def send(self, event):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                await release.wait()
                return DeliveryResult(False, retryable=True)
            return DeliveryResult(True)

    ctx, item_id = delivery_context
    event_id = await enqueue(ctx, item_id, "webhook")
    ctx["notification_channels"] = {"webhook": Receiver()}
    first = asyncio.create_task(deliver_notification(ctx, str(event_id)))
    await asyncio.wait_for(entered.wait(), 5)
    async with ctx["session_factory"]() as session:
        event = await session.get_one(NotificationEvent, event_id)
        later = {**ctx, "notification_now": event.next_attempt_at + timedelta(seconds=1)}
    try:
        assert (await deliver_notification(later, str(event_id)))["status"] == "sent"
    finally:
        release.set()
    assert (await first)["status"] == "lease_lost"
    async with ctx["session_factory"]() as session:
        event = await session.get_one(NotificationEvent, event_id)
        assert (event.status, event.attempt_count) == ("sent", 2)


@pytest.mark.asyncio
async def test_cached_pending_event_is_refreshed_before_reserving_another_attempt(delivery_context):
    from app.notifications.base import DeliveryResult
    from app.workers.notifications import deliver_notification

    sent = []

    class Receiver:
        async def send(self, event):
            sent.append(event.dedupe_key)
            return DeliveryResult(True)

    ctx, item_id = delivery_context
    event_id = await enqueue(ctx, item_id, "webhook")
    ctx["notification_channels"] = {"webhook": Receiver()}
    async with ctx["session_factory"]() as stale_session:
        cached = await stale_session.get_one(NotificationEvent, event_id)
        assert cached.status == "pending"
        await deliver_notification(ctx, str(event_id))
        await deliver_notification({**ctx, "session": stale_session}, str(event_id))
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_concurrent_enqueue_and_delivery_produce_one_durable_local_receipt(delivery_context):
    from app.models import LocalNotificationReceipt
    from app.workers.notifications import deliver_notification

    ctx, item_id = delivery_context
    ids = await asyncio.gather(*(enqueue(ctx, item_id) for _ in range(3)))
    assert len(set(ids)) == 1
    await asyncio.gather(*(deliver_notification(ctx, str(ids[0])) for _ in range(3)))
    async with ctx["session_factory"]() as session:
        event = await session.get_one(NotificationEvent, ids[0])
        assert (event.status, event.attempt_count) == ("sent", 1)
        receipts = list(
            await session.scalars(
                select(LocalNotificationReceipt).where(
                    LocalNotificationReceipt.notification_event_id == event.id
                )
            )
        )
        assert len(receipts) == 1
        assert receipts[0].payload_json == event.payload_json


@pytest.mark.asyncio
async def test_retry_due_time_and_three_attempt_budget_are_durable(delivery_context):
    from app.notifications.base import DeliveryResult
    from app.workers.notifications import deliver_notification

    class Unavailable:
        async def send(self, event):
            return DeliveryResult(success=False, retryable=True, error_code="http_503")

    ctx, item_id = delivery_context
    ctx["notification_channels"] = {"webhook": Unavailable()}
    event_id = await enqueue(ctx, item_id, "webhook")
    now = datetime.now(UTC)
    for attempt in range(1, 4):
        ctx["notification_now"] = now
        result = await deliver_notification(ctx, str(event_id))
        async with ctx["session_factory"]() as session:
            event = await session.get_one(NotificationEvent, event_id)
            failure = await session.scalar(
                select(JobFailure).where(JobFailure.job_key == event.dedupe_key)
            )
            assert event.attempt_count == failure.attempts == attempt
            assert failure.payload_json == {"notification_event_id": str(event_id)}
            if attempt < 3:
                assert result["status"] == "pending"
                assert now + timedelta(seconds=2**attempt) <= event.next_attempt_at
                assert event.next_attempt_at <= now + timedelta(seconds=2**attempt + 1)
                assert failure.next_retry_at == event.next_attempt_at
                assert (await deliver_notification(ctx, str(event_id)))["status"] == "not_due"
                now = event.next_attempt_at
            else:
                assert result["status"] == "dead_lettered"
                assert failure.dead_lettered is True
                assert event.next_attempt_at is None
    assert (await deliver_notification(ctx, str(event_id)))["status"] == "dead_lettered"


@pytest.mark.asyncio
async def test_terminal_failure_redacts_exception_and_unconfigured_email(delivery_context):
    from app.workers.notifications import deliver_notification

    ctx, item_id = delivery_context
    event_id = await enqueue(ctx, item_id, "email")
    result = await deliver_notification(ctx, str(event_id))
    assert result["status"] == "dead_lettered"
    async with ctx["session_factory"]() as session:
        failure = await session.scalar(
            select(JobFailure).where(
                JobFailure.payload_json["notification_event_id"].astext == str(event_id)
            )
        )
        assert failure.attempts == 1
        assert failure.error_message == "channel_not_configured"


@pytest.mark.asyncio
async def test_cancelled_reserved_attempt_recovers_after_lease_without_resetting_budget(
    delivery_context,
):
    from app.notifications.base import DeliveryResult
    from app.workers.notifications import deliver_notification

    entered = asyncio.Event()

    class Cancelled:
        async def send(self, event):
            entered.set()
            await asyncio.Event().wait()
            return DeliveryResult(success=True)

    ctx, item_id = delivery_context
    ctx["notification_channels"] = {"webhook": Cancelled()}
    event_id = await enqueue(ctx, item_id, "webhook")
    task = asyncio.create_task(deliver_notification(ctx, str(event_id)))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with ctx["session_factory"]() as session:
        event = await session.get_one(NotificationEvent, event_id)
        assert event.status == "sending" and event.attempt_count == 1
        ctx["notification_now"] = event.next_attempt_at + timedelta(seconds=1)
    ctx["notification_channels"] = {}
    result = await deliver_notification(ctx, str(event_id))
    assert result["status"] == "dead_lettered"
    async with ctx["session_factory"]() as session:
        event = await session.get_one(NotificationEvent, event_id)
        assert event.attempt_count == 2


@pytest.mark.asyncio
async def test_enqueue_rollback_has_no_deliverable_event(delivery_context):
    from app.notifications.service import enqueue_notification

    ctx, item_id = delivery_context
    async with ctx["session_factory"]() as session:
        await enqueue_notification(
            session,
            user_id="owner",
            opportunity_id=item_id,
            channel="local",
            template_key="new_high_relevance",
            semantic_identity={},
            payload={},
        )
        await session.rollback()
    async with ctx["session_factory"]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NotificationEvent)
                .where(NotificationEvent.opportunity_id == item_id)
            )
            == 0
        )
