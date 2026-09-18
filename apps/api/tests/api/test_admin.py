from uuid import uuid4

import pytest

from app.models import JobFailure
from tests.api.test_opportunities import login


@pytest.mark.asyncio
async def test_release_is_typed_public_and_ready_is_distinct():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        release = await http.get("/api/v1/release")
        assert release.status_code == 200
        assert release.json()["authentication"] == "synthetic-demo-nonproduction"
        assert (await http.get("/health/live")).status_code == 200


@pytest.mark.asyncio
async def test_admin_database_counts_safe_errors_resolved_exclusion_and_retry(client, session):
    await login(client, operator=True)
    before = (await client.get("/api/v1/admin/pipeline")).json()
    failure = JobFailure(
        job_type="poll_source",
        job_key=uuid4().hex,
        attempts=3,
        dead_lettered=True,
        error_class="TimeoutError",
        error_message="secret=never-expose",
        payload_json={"source_code": "mock", "secret": "never-expose"},
    )
    resolved = JobFailure(
        job_type="poll_source",
        job_key=uuid4().hex,
        attempts=0,
        dead_lettered=False,
        error_class="TimeoutError",
        error_message="never-expose",
        payload_json={},
    )
    session.add_all([failure, resolved])
    await session.flush()
    after = await client.get("/api/v1/admin/pipeline")
    assert after.status_code == 200, after.text
    assert after.json()["dlq_count"] == before["dlq_count"] + 1
    failures = await client.get("/api/v1/admin/failures")
    assert "never-expose" not in failures.text
    assert str(failure.id) in failures.text and str(resolved.id) not in failures.text
    retried = await client.post(f"/api/v1/admin/failures/{failure.id}/retry")
    assert retried.status_code == 202, retried.text
    await session.refresh(failure)
    assert failure.dead_lettered is False and failure.next_retry_at is not None
    assert failure.attempts == 0


@pytest.mark.asyncio
async def test_admin_retry_is_rate_limited_and_has_no_owner_override(client):
    await login(client, operator=True)
    statuses = [
        (await client.post(f"/api/v1/admin/failures/{uuid4()}/retry")).status_code for _ in range(6)
    ]
    assert statuses == [404] * 5 + [429]


@pytest.mark.asyncio
async def test_notification_retry_resets_both_rows_and_preserves_identity(
    client, session, opportunities
):
    from app.models import LocalNotificationReceipt, NotificationEvent

    actor = await login(client, operator=True)
    event = NotificationEvent(
        user_id=actor["owner_id"],
        opportunity_id=opportunities[0].id,
        channel="local",
        template_key="new_high_relevance",
        dedupe_key=uuid4().hex,
        status="dead_lettered",
        attempt_count=3,
        payload_json={"synthetic": True},
    )
    session.add(event)
    await session.flush()
    failure = JobFailure(
        job_type="deliver_notification",
        job_key=event.dedupe_key,
        attempts=3,
        dead_lettered=True,
        error_class="NotificationDeliveryError",
        error_message="delivery_failed",
        payload_json={"notification_event_id": str(event.id)},
    )
    session.add(failure)
    await session.flush()
    identity = event.dedupe_key
    response = await client.post(f"/api/v1/admin/failures/{failure.id}/retry")
    assert response.status_code == 202, response.text
    await session.refresh(event)
    await session.refresh(failure)
    assert event.attempt_count == failure.attempts == 0
    assert event.status == "pending" and failure.dead_lettered is False
    assert event.dedupe_key == identity and event.next_attempt_at is not None
    event.status = "dead_lettered"
    failure.dead_lettered = True
    session.add(LocalNotificationReceipt(notification_event_id=event.id, payload_json={}))
    await session.flush()
    assert (await client.post(f"/api/v1/admin/failures/{failure.id}/retry")).status_code == 409


@pytest.mark.asyncio
async def test_readiness_checks_schema_storage_redis_and_workers(client, monkeypatch):
    from app.api.auth import get_redis
    from app.main import app

    class ReadyRedis:
        async def ping(self):
            return True

        async def exists(self, key):
            return True

    async def healthy():
        yield ReadyRedis()

    app.dependency_overrides[get_redis] = healthy
    response = await client.get("/health/ready")
    assert response.status_code == 200, response.text
    assert all(response.json()["dependencies"].values())

    class BrokenRedis(ReadyRedis):
        async def ping(self):
            raise ConnectionError("secret-unreachable")

    async def broken():
        yield BrokenRedis()

    app.dependency_overrides[get_redis] = broken
    response = await client.get("/health/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["redis"] is False
    assert "secret-unreachable" not in response.text
    assert (await client.get("/health/live")).status_code == 200


@pytest.mark.asyncio
async def test_recovered_notification_failure_is_not_pending(client, session, opportunities):
    from app.models import NotificationEvent
    from app.workers.notifications import deliver_notification

    actor = await login(client, operator=True)
    event = NotificationEvent(
        user_id=actor["owner_id"],
        opportunity_id=opportunities[0].id,
        channel="local",
        template_key="new_high_relevance",
        dedupe_key=uuid4().hex,
        status="pending",
        attempt_count=1,
        payload_json={},
    )
    session.add(event)
    await session.flush()
    failure = JobFailure(
        job_type="deliver_notification",
        job_key=event.dedupe_key,
        attempts=1,
        dead_lettered=False,
        error_class="NotificationDeliveryError",
        error_message="transport_error",
        payload_json={"notification_event_id": str(event.id)},
    )
    session.add(failure)
    await session.flush()
    outcome = await deliver_notification({"session": session}, str(event.id))
    assert outcome["status"] == "sent"
    await session.refresh(failure)
    assert failure.attempts == 0
    await session.refresh(event)
    assert event.attempt_count == 2
    response = await client.get("/api/v1/admin/failures")
    assert str(failure.id) not in response.text


@pytest.mark.asyncio
async def test_pipeline_reports_actual_arq_process_counters(client, monkeypatch):
    from arq.connections import ArqRedis

    from app.api import admin

    original = ArqRedis.get

    async def heartbeat(self, key):
        if key == admin.WORKER_QUEUE + ":health-check":
            return b"Sep-16 12:00:00 j_complete=7 j_failed=2 j_retried=1 j_ongoing=3 queued=4"
        return await original(self, key)

    monkeypatch.setattr(ArqRedis, "get", heartbeat)
    await login(client, operator=True)
    response = await client.get("/api/v1/admin/pipeline")
    assert response.status_code == 200
    assert response.json()["worker_activity"] == {
        "completed": 7,
        "failed": 2,
        "retried": 1,
        "ongoing": 3,
    }


@pytest.mark.asyncio
async def test_queue_outage_keeps_retry_durable_for_reconciler(client, session, monkeypatch):
    from arq.connections import ArqRedis
    from redis.exceptions import ConnectionError

    from app.api import admin
    from app.config import get_settings
    from app.workers import jobs

    await login(client, operator=True)
    failure = JobFailure(
        job_type="poll_source",
        job_key=uuid4().hex,
        attempts=3,
        dead_lettered=True,
        error_class="TimeoutError",
        error_message="safe",
        payload_json={"source_code": "mock"},
    )
    session.add(failure)
    await session.flush()
    original = ArqRedis.enqueue_job

    async def unavailable(*args, **kwargs):
        raise ConnectionError("private redis error")

    monkeypatch.setattr(ArqRedis, "enqueue_job", unavailable)
    response = await client.post(f"/api/v1/admin/failures/{failure.id}/retry")
    assert response.status_code == 202 and response.json()["queue_published"] is False
    assert "private redis" not in response.text
    await session.refresh(failure)
    assert failure.next_retry_at is not None and failure.dead_lettered is False
    monkeypatch.setattr(ArqRedis, "enqueue_job", original)
    monkeypatch.setattr(jobs, "WORKER_QUEUE", admin.WORKER_QUEUE)
    redis = ArqRedis.from_url(get_settings().redis_url)
    try:
        outcome = await jobs.reconcile_failed_jobs({"session": session, "redis": redis})
        assert outcome["requeued"] >= 1
        assert await redis.zscore(admin.WORKER_QUEUE, failure.job_key) is not None
    finally:
        await redis.aclose()
