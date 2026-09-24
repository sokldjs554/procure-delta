from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from arq import Retry
from arq.connections import ArqRedis
from sqlalchemy import select, update

from app.config import get_settings
from app.credits.extraction import ExtractionCreditInProgress, ExtractionCreditPolicy
from app.extraction.hosted import configured_extractor
from app.extraction.service import build_document_bundle, extraction_identity, persist_extraction
from app.models import JobFailure, OpportunityVersion, StructuredExtraction
from app.workers.jobs import (
    MAX_ATTEMPTS,
    WORKER_QUEUE,
    _is_transient,
    _record_failure,
    _session_scope,
    job_key,
)


async def extract_version(
    ctx: dict[str, Any],
    version_id: str,
    expected_key: str | None = None,
) -> dict[str, str]:
    settings = get_settings()
    extractor = ctx.get("extractor") or configured_extractor(settings)
    credit_policy = ExtractionCreditPolicy.from_settings(settings)
    stable_key = job_key(
        "extract_version", "attachment", {"version_id": version_id, "key": expected_key}
    )
    async with _session_scope(ctx) as session:
        try:
            identifier = UUID(version_id)
            document = await build_document_bundle(session, identifier)
            if not document.pages:
                return {"status": "no_suitable_pages", "job_key": stable_key}
            key = extraction_identity(document, extractor)
            stable_key = job_key(
                "extract_version", "attachment", {"version_id": version_id, "key": key}
            )
            if expected_key is not None and expected_key != key:
                return {"status": "stale", "job_key": stable_key}
            failure = await session.scalar(
                select(JobFailure).where(
                    JobFailure.job_type == "extract_version", JobFailure.job_key == stable_key
                )
            )
            if failure is not None and failure.attempts > 0:
                if failure.dead_lettered or failure.attempts >= MAX_ATTEMPTS:
                    return {"status": "dead_lettered", "job_key": stable_key}
                if failure.next_retry_at is not None and failure.next_retry_at > datetime.now(UTC):
                    return {"status": "deferred", "job_key": stable_key}
            result = await persist_extraction(
                session, identifier, extractor, expected_key=key, credit_policy=credit_policy,
            )
            status = result.validation_status if result is not None else "stale"
            await session.execute(
                update(JobFailure)
                .where(
                    JobFailure.job_type == "extract_version",
                    JobFailure.job_key == stable_key,
                )
                .values(attempts=0, dead_lettered=False, next_retry_at=None)
            )
            await session.commit()
            return {"status": status, "job_key": stable_key}
        except ExtractionCreditInProgress:
            # The owner released its version lock when making the hold durable.
            # A duplicate in that gap must not leave a false terminal failure.
            await session.rollback()
            return {"status": "deferred", "job_key": stable_key}
        except Exception as error:
            # Snapshot only primitive identifiers above: rollback expires loaded ORM objects.
            await session.rollback()
            failure = await _record_failure(
                session,
                job_type="extract_version",
                stable_key=stable_key,
                payload={"version_id": version_id, "expected_key": expected_key},
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


async def reconcile_pending_extractions(ctx: dict[str, Any]) -> dict[str, int]:
    """Find absent durable results after restarts; rejected results are completed work."""
    extractor = ctx.get("extractor") or configured_extractor(get_settings())
    pending: list[tuple[str, str, str]] = []
    async with _session_scope(ctx) as session:
        ids = list(
            await session.scalars(select(OpportunityVersion.id).order_by(OpportunityVersion.id))
        )
        for identifier in ids:
            document = await build_document_bundle(session, identifier)
            if not document.pages:
                continue
            key = extraction_identity(document, extractor)
            existing = await session.scalar(
                select(StructuredExtraction.id).where(
                    StructuredExtraction.opportunity_version_id == identifier,
                    StructuredExtraction.extraction_key == key,
                )
            )
            stable_key = job_key(
                "extract_version", "attachment", {"version_id": str(identifier), "key": key}
            )
            failure = await session.scalar(
                select(JobFailure).where(
                    JobFailure.job_type == "extract_version", JobFailure.job_key == stable_key
                )
            )
            if existing is not None:
                continue
            if (
                failure is not None
                and failure.attempts > 0
                and (
                    failure.dead_lettered
                    or failure.attempts >= MAX_ATTEMPTS
                    or failure.next_retry_at is None
                    or failure.next_retry_at > datetime.now(UTC)
                )
            ):
                continue
            pending.append((str(identifier), key, stable_key))
    processed = failed = queued = 0
    redis = ctx.get("redis")
    for version_id, key, stable_key in pending:
        if isinstance(redis, ArqRedis):
            enqueued = await redis.enqueue_job(
                "extract_version", version_id, key, _job_id=stable_key, _queue_name=WORKER_QUEUE
            )
            queued += enqueued is not None
            continue
        try:
            outcome = await extract_version(ctx, version_id, key)
            processed += outcome["status"] in {"validated", "rejected"}
            failed += outcome["status"] == "dead_lettered"
        except Retry:
            failed += 1
    return {"processed": processed, "failed": failed, "queued": queued}
