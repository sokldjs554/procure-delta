from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from arq import Retry
from arq.connections import ArqRedis
from sqlalchemy import select, update

from app.config import get_settings
from app.delta.service import persist_delta
from app.extraction.hosted import configured_extractor
from app.models import JobFailure, OpportunityVersion
from app.workers.jobs import (
    MAX_ATTEMPTS,
    WORKER_QUEUE,
    _is_transient,
    _record_failure,
    _session_scope,
    job_key,
)


async def compute_opportunity_delta(ctx: dict[str, Any], to_version_id: str) -> dict[str, str]:
    stable_key = job_key("compute_opportunity_delta", "version", {"to_version_id": to_version_id})
    extractor = ctx.get("extractor") or configured_extractor(get_settings())
    async with _session_scope(ctx) as session:
        try:
            failure = await session.scalar(
                select(JobFailure).where(
                    JobFailure.job_type == "compute_opportunity_delta",
                    JobFailure.job_key == stable_key,
                )
            )
            if failure is not None and failure.attempts > 0:
                if failure.dead_lettered or failure.attempts >= MAX_ATTEMPTS:
                    return {"status": "dead_lettered", "job_key": stable_key}
                if failure.next_retry_at is not None and failure.next_retry_at > datetime.now(UTC):
                    return {"status": "deferred", "job_key": stable_key}
            status, delta = await persist_delta(session, UUID(to_version_id), extractor)
            delta_id = str(delta.id) if delta is not None else ""
            await session.execute(
                update(JobFailure)
                .where(
                    JobFailure.job_type == "compute_opportunity_delta",
                    JobFailure.job_key == stable_key,
                )
                .values(attempts=0, dead_lettered=False, next_retry_at=None)
            )
            await session.commit()
            return {"status": status, "job_key": stable_key, "delta_id": delta_id}
        except Exception as error:
            await session.rollback()
            failure = await _record_failure(
                session,
                job_type="compute_opportunity_delta",
                stable_key=stable_key,
                payload={"to_version_id": to_version_id},
                error=error,
                dead_lettered=not _is_transient(error),
            )
            attempts = failure.attempts
            terminal = failure.dead_lettered or attempts >= MAX_ATTEMPTS
            if terminal:
                failure.dead_lettered = True
                failure.next_retry_at = None
            await session.commit()
            if terminal:
                return {"status": "dead_lettered", "job_key": stable_key}
            raise Retry(defer=2**attempts) from error


async def reconcile_pending_deltas(ctx: dict[str, Any]) -> dict[str, int]:
    """Database-driven reconciliation survives Redis job/result expiry and worker restarts."""
    pending: list[tuple[str, str]] = []
    async with _session_scope(ctx) as session:
        ids = list(
            await session.scalars(
                select(OpportunityVersion.id)
                .where(OpportunityVersion.version_number > 1)
                .order_by(OpportunityVersion.id)
            )
        )
        for identifier in ids:
            stable_key = job_key(
                "compute_opportunity_delta", "version", {"to_version_id": str(identifier)}
            )
            failure = await session.scalar(
                select(JobFailure).where(
                    JobFailure.job_type == "compute_opportunity_delta",
                    JobFailure.job_key == stable_key,
                )
            )
            if (
                failure is not None
                and failure.attempts > 0
                and (
                    failure.dead_lettered
                    or failure.attempts >= MAX_ATTEMPTS
                    or (
                        failure.next_retry_at is not None
                        and failure.next_retry_at > datetime.now(UTC)
                    )
                )
            ):
                continue
            pending.append((str(identifier), stable_key))
    created = queued = failed = 0
    for pending_id, stable_key in pending:
        redis = ctx.get("redis")
        if isinstance(redis, ArqRedis):
            enqueued = await redis.enqueue_job(
                "compute_opportunity_delta",
                pending_id,
                _job_id=stable_key,
                _queue_name=WORKER_QUEUE,
            )
            queued += enqueued is not None
        else:
            try:
                result = await compute_opportunity_delta(ctx, pending_id)
                created += result["status"] == "created"
                failed += result["status"] == "dead_lettered"
            except Retry:
                failed += 1
    return {"created": created, "queued": queued, "failed": failed}
