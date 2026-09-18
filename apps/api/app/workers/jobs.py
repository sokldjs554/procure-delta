from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from arq import Retry
from arq.connections import ArqRedis
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db import SessionLocal
from app.documents.service import (
    complete_document_generation,
    materialize_attachment_refs,
    persist_and_parse_attachments,
)
from app.models import IngestRun, JobFailure, OpportunityVersion, RawRecord, SourceRegistry
from app.repositories.opportunities import upsert_opportunity_version
from app.services.ingest import ingest_raw_record
from app.services.normalize import normalize_raw_record
from app.sources.base import RawSourceRecord, SourceAdapter
from app.sources.koneps import BASE_URL, DOCUMENT_HOST, SOURCE_CODE, KonepsSourceAdapter
from app.sources.mock import MockSourceAdapter

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
WORKER_QUEUE = "arq:procure-delta:worker"


class MalformedJobError(ValueError):
    """A payload that cannot succeed until an operator changes it."""


def _safe_error_message(error: Exception) -> str:
    """Persist only bounded, non-secret failure facts for later operator review."""
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTPStatusError(status={error.response.status_code})"
    return type(error).__name__


def job_key(job_type: str, source_code: str, payload: dict[str, Any]) -> str:
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    value = f"{job_type}\x00{source_code}\x00{canonical_payload}".encode()
    return hashlib.sha256(value).hexdigest()


def source_adapters() -> dict[str, SourceAdapter]:
    adapters: dict[str, SourceAdapter] = {"mock": MockSourceAdapter()}
    settings = get_settings()
    if settings.koneps_enabled:
        key = settings.koneps_service_key
        if key is None or not key.get_secret_value().strip():
            raise ValueError("KONEPS_SERVICE_KEY is required when KONEPS_ENABLED=true")
        adapters[SOURCE_CODE] = KonepsSourceAdapter(
            service_key=key.get_secret_value(), lookback_days=settings.koneps_lookback_days,
        )
    return adapters


async def poll_configured_sources(ctx: dict[str, Any]) -> dict[str, str]:
    results = {}
    for code in source_adapters():
        try:
            results[code] = (await poll_source(ctx, code))["status"]
        except Retry:
            # poll_source has already persisted its retry; other sources still get their turn.
            results[code] = "retry_pending"
    return results


@asynccontextmanager
async def _session_scope(ctx: dict[str, Any]) -> AsyncIterator[AsyncSession]:
    supplied = ctx.get("session")
    if isinstance(supplied, AsyncSession):
        yield supplied
        return
    factory = ctx.get("session_factory", SessionLocal)
    if not isinstance(factory, async_sessionmaker):
        # Tests and app startup both use SQLAlchemy session makers; reject ambiguous fakes.
        raise TypeError("session_factory must be an async_sessionmaker")
    async with factory() as session:
        yield session


async def _record_failure(
    session: AsyncSession,
    *,
    job_type: str,
    stable_key: str,
    payload: dict[str, Any],
    error: Exception,
    dead_lettered: bool,
) -> JobFailure:
    now = datetime.now(UTC)
    retry_at = None if dead_lettered else now + timedelta(seconds=2)
    statement = (
        insert(JobFailure)
        .values(
            job_type=job_type,
            job_key=stable_key,
            attempts=1,
            error_class=type(error).__name__,
            error_message=_safe_error_message(error),
            last_error_at=now,
            payload_json=payload,
            dead_lettered=dead_lettered,
            next_retry_at=retry_at,
        )
        .on_conflict_do_update(
            constraint="uq_job_failure_type_key",
            set_={
                "attempts": JobFailure.attempts + 1,
                "error_class": type(error).__name__,
                "error_message": _safe_error_message(error),
                "last_error_at": now,
                "payload_json": payload,
                "dead_lettered": dead_lettered,
                "next_retry_at": retry_at,
            },
        )
        .returning(JobFailure.id)
    )
    failure_id = (await session.execute(statement)).scalar_one()
    return await session.get_one(JobFailure, failure_id, populate_existing=True)


def _is_transient(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == 429 or error.response.status_code >= 500
    if isinstance(error, DBAPIError):
        sqlstate = getattr(error.orig, "sqlstate", None)
        if isinstance(sqlstate, str):
            return sqlstate.startswith("08") or sqlstate in {"40001", "40P01"}
        return isinstance(error, OperationalError)
    return isinstance(
        error,
        (
            httpx.TimeoutException,
            httpx.NetworkError,
            OSError,
            asyncio.TimeoutError,
            RedisError,
        ),
    )


async def ingest_record(
    ctx: dict[str, Any], source_code: str, payload: dict[str, Any]
) -> dict[str, str]:
    started = time.perf_counter()
    replay_payload = {"source_code": source_code, **payload}
    stable_key = job_key("ingest_record", source_code, replay_payload)
    raw_record_id = None
    try:
        record = RawSourceRecord.model_validate(payload)
    except ValidationError as error:
        async with _session_scope(ctx) as session:
            await _record_failure(
                session,
                job_type="ingest_record",
                stable_key=stable_key,
                payload=replay_payload,
                error=MalformedJobError(str(error)),
                dead_lettered=True,
            )
            await session.commit()
        return {"status": "dead_lettered", "job_key": stable_key}

    try:
        async with _session_scope(ctx) as session:
            source = await session.scalar(
                select(SourceRegistry).where(SourceRegistry.code == source_code)
            )
            if source is None:
                raise MalformedJobError(f"unknown source: {source_code}")
            outcome = await ingest_raw_record(session, source.id, record)
            raw_record_id = outcome.raw_record_id
            await session.commit()
            try:
                await _normalize_persisted_raw(session, outcome.raw_record_id)
                await session.commit()
            except Exception as error:
                await session.rollback()
                failed_raw = await session.get(RawRecord, outcome.raw_record_id)
                if failed_raw is not None:
                    failed_raw.normalization_status = (
                        "pending" if _is_transient(error) else "failed"
                    )
                raise
            await session.execute(
                update(JobFailure)
                .where(JobFailure.job_type == "ingest_record", JobFailure.job_key == stable_key)
                .values(attempts=0, dead_lettered=False, next_retry_at=None)
            )
            await session.commit()
        return {"status": "created" if outcome.created else "duplicate", "job_key": stable_key}
    except MalformedJobError as error:
        async with _session_scope(ctx) as session:
            await _record_failure(
                session,
                job_type="ingest_record",
                stable_key=stable_key,
                payload=replay_payload,
                error=error,
                dead_lettered=True,
            )
            await session.commit()
        return {"status": "dead_lettered", "job_key": stable_key}
    except Exception as error:
        if not _is_transient(error):
            async with _session_scope(ctx) as session:
                if raw_record_id is not None:
                    failed_raw = await session.get(RawRecord, raw_record_id)
                    if failed_raw is not None:
                        failed_raw.normalization_status = "failed"
                await _record_failure(
                    session,
                    job_type="ingest_record",
                    stable_key=stable_key,
                    payload={
                        **replay_payload,
                        **(
                            {"raw_record_id": str(raw_record_id)}
                            if raw_record_id is not None
                            else {}
                        ),
                    },
                    error=error,
                    dead_lettered=True,
                )
                await session.commit()
            return {"status": "dead_lettered", "job_key": stable_key}
        async with _session_scope(ctx) as session:
            if raw_record_id is not None:
                pending_raw = await session.get(RawRecord, raw_record_id)
                if pending_raw is not None:
                    pending_raw.normalization_status = "pending"
            failure = await _record_failure(
                session,
                job_type="ingest_record",
                stable_key=stable_key,
                payload={
                    **replay_payload,
                    **({"raw_record_id": str(raw_record_id)} if raw_record_id is not None else {}),
                },
                error=error,
                dead_lettered=False,
            )
            terminal = failure.attempts >= MAX_ATTEMPTS
            if terminal:
                failure.dead_lettered = True
                failure.next_retry_at = None
            await session.commit()
        if terminal:
            return {"status": "dead_lettered", "job_key": stable_key}
        raise Retry(defer=2**failure.attempts) from error
    finally:
        logger.info(
            "ingest_job",
            extra={
                "source": source_code,
                "stage": "raw_ingest",
                "job_key": stable_key,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )


async def poll_source(ctx: dict[str, Any], source_code: str = "mock") -> dict[str, str]:
    started = time.perf_counter()
    adapter = source_adapters().get(source_code)
    if adapter is None:
        raise MalformedJobError(f"unknown source adapter: {source_code}")
    stable_key = job_key("poll_source", source_code, {"source_code": source_code})
    run_id = None
    try:
        async with _session_scope(ctx) as session:
            await session.execute(
                insert(SourceRegistry)
                .values(
                    code=source_code,
                    display_name=(
                        "KONEPS service tenders"
                        if source_code == SOURCE_CODE
                        else "Synthetic mock source"
                    ),
                    base_url=BASE_URL if source_code == SOURCE_CODE else "https://example.invalid",
                )
                .on_conflict_do_nothing(index_elements=[SourceRegistry.code])
            )
            source = await session.scalar(
                select(SourceRegistry).where(SourceRegistry.code == source_code)
            )
            assert source is not None
            if not source.enabled:
                return {"status": "disabled", "source": source_code}
            await session.commit()
            latest = await session.scalar(
                select(IngestRun)
                .where(IngestRun.source_id == source.id, IngestRun.status == "success")
                .order_by(IngestRun.finished_at.desc())
                .limit(1)
            )
            cursor = latest.cursor_after if latest is not None else None
            run = IngestRun(source_id=source.id, status="running", cursor_before=cursor)
            session.add(run)
            await session.flush()
            run_id = run.id
            await session.commit()
            page = await adapter.discover(cursor)
            for record in page.records:
                await ingest_raw_record(session, source.id, record, ingest_run=run)
            run.fetched_count = len(page.records)
            run.cursor_after = page.next_cursor
            run.status = "success"
            run.finished_at = datetime.now(UTC)
            source.last_success_at = run.finished_at
            await session.execute(
                update(JobFailure)
                .where(JobFailure.job_type == "poll_source", JobFailure.job_key == stable_key)
                .values(attempts=0, dead_lettered=False, next_retry_at=None)
            )
            await session.commit()
            pending_ids = (
                await session.scalars(
                    select(RawRecord.id).where(
                        RawRecord.source_id == source.id,
                        RawRecord.normalization_status == "pending",
                    )
                )
            ).all()
            for raw_id in pending_ids:
                try:
                    await _normalize_persisted_raw(session, raw_id)
                    await session.commit()
                except Exception as error:
                    await session.rollback()
                    failed_raw = await session.get(RawRecord, raw_id)
                    failure = await _record_normalization_failure(session, raw_id, error)
                    if failed_raw is not None and failure.dead_lettered:
                        failed_raw.normalization_status = "failed"
                    await session.execute(
                        update(IngestRun)
                        .where(IngestRun.id == run_id)
                        .values(failure_count=IngestRun.failure_count + 1)
                    )
                    logger.warning(
                        "normalization_rejected",
                        extra={"raw_record_id": str(raw_id), "error": _safe_error_message(error)},
                    )
                    await session.commit()
    except Exception as error:
        async with _session_scope(ctx) as failure_session:
            source = await failure_session.scalar(
                select(SourceRegistry).where(SourceRegistry.code == source_code)
            )
            if source is not None:
                source.last_failure_at = datetime.now(UTC)
                failed_run = (
                    await failure_session.get(IngestRun, run_id) if run_id is not None else None
                )
                if failed_run is not None:
                    failed_run.status = "failed"
                    failed_run.failure_count += 1
                    failed_run.finished_at = datetime.now(UTC)
            failure = await _record_failure(
                failure_session,
                job_type="poll_source",
                stable_key=stable_key,
                payload={"source_code": source_code},
                error=error,
                dead_lettered=not _is_transient(error),
            )
            terminal = failure.attempts >= MAX_ATTEMPTS
            if terminal:
                failure.dead_lettered = True
                failure.next_retry_at = None
            await failure_session.commit()
        if _is_transient(error) and not terminal:
            raise Retry(defer=2**failure.attempts) from error
        return {"status": "dead_lettered", "job_key": stable_key}
    logger.info(
        "source_poll",
        extra={
            "source": source_code,
            "stage": "discovery",
            "attempt": 1,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "result": "success",
        },
    )
    return {"status": "success", "source": source_code}


async def reconcile_failed_jobs(ctx: dict[str, Any]) -> dict[str, int]:
    """Re-enqueue durable retryable failures without touching terminal DLQ entries."""
    async with _session_scope(ctx) as session:
        now = datetime.now(UTC)
        failures = (
            await session.scalars(
                select(JobFailure).where(
                    JobFailure.dead_lettered.is_(False), JobFailure.next_retry_at <= now
                )
            )
        ).all()
        redis = ctx.get("redis")
        if not isinstance(redis, ArqRedis):
            return {"requeued": 0}
        requeued = 0
        for failure in failures:
            source_code = str(failure.payload_json.get("source_code", "mock"))
            payload = dict(failure.payload_json)
            payload.pop("source_code", None)
            payload.pop("raw_record_id", None)
            if failure.job_type == "ingest_record":
                enqueued = await redis.enqueue_job(
                    "ingest_record",
                    source_code,
                    payload,
                    _job_id=failure.job_key,
                    _queue_name=WORKER_QUEUE,
                )
            elif failure.job_type == "poll_source":
                enqueued = await redis.enqueue_job(
                    "poll_source",
                    source_code,
                    _job_id=failure.job_key,
                    _queue_name=WORKER_QUEUE,
                )
            else:
                continue
            if enqueued is not None:
                failure.next_retry_at = now + timedelta(seconds=2**failure.attempts)
                requeued += 1
        await session.commit()
    return {"requeued": requeued}


async def _normalize_persisted_raw(session: AsyncSession, raw_record_id: Any) -> None:
    raw = await session.get_one(RawRecord, raw_record_id)
    if raw.normalization_status == "normalized":
        return
    source = await session.get_one(SourceRegistry, raw.source_id)
    normalized = normalize_raw_record(raw, source_code=source.code)
    await upsert_opportunity_version(session, raw, normalized)
    stable_key = job_key("normalize_record", "raw", {"raw_record_id": str(raw_record_id)})
    await session.execute(
        update(JobFailure)
        .where(JobFailure.job_type == "normalize_record", JobFailure.job_key == stable_key)
        .values(attempts=0, dead_lettered=False, next_retry_at=None)
    )
    await session.execute(
        update(JobFailure)
        .where(
            JobFailure.job_type == "ingest_record",
            JobFailure.payload_json["raw_record_id"].astext == str(raw_record_id),
        )
        .values(attempts=0, dead_lettered=False, next_retry_at=None)
    )


async def _record_normalization_failure(
    session: AsyncSession, raw_record_id: Any, error: Exception
) -> JobFailure:
    stable_key = job_key("normalize_record", "raw", {"raw_record_id": str(raw_record_id)})
    retryable = _is_transient(error)
    failure = await _record_failure(
        session,
        job_type="normalize_record",
        stable_key=stable_key,
        payload={"raw_record_id": str(raw_record_id)},
        error=error,
        dead_lettered=not retryable,
    )
    if retryable and failure.attempts >= MAX_ATTEMPTS:
        failure.dead_lettered = True
        failure.next_retry_at = None
    return failure


async def reconcile_pending_normalizations(ctx: dict[str, Any]) -> dict[str, int]:
    """Recover raw-first commits interrupted before normalization."""
    normalized = 0
    failed = 0
    async with _session_scope(ctx) as session:
        raw_ids = (
            await session.scalars(
                select(RawRecord.id).where(RawRecord.normalization_status == "pending")
            )
        ).all()
        for raw_id in raw_ids:
            try:
                await _normalize_persisted_raw(session, raw_id)
                await session.commit()
                normalized += 1
            except Exception as error:
                await session.rollback()
                raw = await session.get(RawRecord, raw_id)
                failure = await _record_normalization_failure(session, raw_id, error)
                if raw is not None and failure.dead_lettered:
                    raw.normalization_status = "failed"
                logger.warning(
                    "normalization_rejected",
                    extra={"raw_record_id": str(raw_id), "error": _safe_error_message(error)},
                )
                await session.commit()
                failed += 1
    return {"normalized": normalized, "failed": failed}


async def reconcile_pending_documents(ctx: dict[str, Any]) -> dict[str, int]:
    """Recover the normalized-version document pipeline from durable database state."""
    processed = 0
    failed = 0
    settings = get_settings()
    storage_root = Path(ctx.get("attachment_storage_path", settings.attachment_storage_path))
    now = datetime.now(UTC)
    async with _session_scope(ctx) as discovery_session:
        rows = (
            await discovery_session.execute(
                select(
                    RawRecord.id,
                    RawRecord.source_record_id,
                    RawRecord.payload_json,
                    RawRecord.http_etag,
                    RawRecord.http_last_modified,
                    RawRecord.source_updated_at,
                    OpportunityVersion.id,
                    OpportunityVersion.documents_generation,
                    SourceRegistry.code,
                    SourceRegistry.base_url,
                )
                .join(OpportunityVersion, OpportunityVersion.raw_record_id == RawRecord.id)
                .join(SourceRegistry, SourceRegistry.id == RawRecord.source_id)
                .where(RawRecord.normalization_status == "normalized")
                .order_by(RawRecord.id)
            )
        ).all()
    for row in rows:
        (
            raw_id,
            source_record_id,
            payload_json,
            http_etag,
            http_last_modified,
            source_updated_at,
            version_id,
            processing_generation,
            source_code,
            source_base_url,
        ) = row
        stable_key = job_key("parse_documents", source_code, {"raw_record_id": str(raw_id)})
        retrying_generation = False
        async with _session_scope(ctx) as state_session:
            current = (
                await state_session.scalars(
                    select(OpportunityVersion)
                    .where(OpportunityVersion.id == version_id)
                    .with_for_update()
                )
            ).one()
            processing_generation = current.documents_generation
            failure = await state_session.scalar(
                select(JobFailure).where(
                    JobFailure.job_type == "parse_documents", JobFailure.job_key == stable_key
                )
            )
            generation_value = str(processing_generation) if processing_generation else None
            if (
                failure is not None
                and failure.payload_json.get("documents_generation") != generation_value
            ):
                # A deliberate repair owns a new retry budget; old DLQ/backoff cannot gate it.
                failure.attempts = 0
                failure.dead_lettered = False
                failure.next_retry_at = None
                failure.payload_json = {
                    **failure.payload_json,
                    "documents_generation": generation_value,
                }
            if failure is not None and failure.attempts > 0:
                retrying_generation = True
                terminal = failure.dead_lettered or failure.attempts >= MAX_ATTEMPTS
                if terminal or failure.next_retry_at is None or failure.next_retry_at > now:
                    if terminal:
                        await complete_document_generation(
                            state_session,
                            opportunity_version_id=version_id,
                            generation=processing_generation,
                            gaps={
                                "stage": "documents",
                                "status": "dead_lettered",
                                "job_key": stable_key,
                            },
                        )
                    await state_session.commit()
                    continue
            await state_session.commit()
        adapter = source_adapters().get(source_code)
        if adapter is None:
            continue
        record = RawSourceRecord(
            source_record_id=source_record_id,
            raw_payload=payload_json,
            http_etag=http_etag,
            http_last_modified=http_last_modified,
            source_updated_at=source_updated_at,
        )
        try:
            refs = await adapter.fetch_attachments(record)
            async with _session_scope(ctx) as staging_session:
                staged = (
                    await staging_session.scalars(
                        select(OpportunityVersion)
                        .where(OpportunityVersion.id == version_id)
                        .with_for_update()
                    )
                ).one()
                if staged.documents_generation != processing_generation:
                    continue  # Discovery completed after a newer repair took ownership.
                await materialize_attachment_refs(
                    staging_session,
                    opportunity_version_id=version_id,
                    refs=refs,
                    processing_generation=processing_generation if retrying_generation else None,
                )
                processing_generation = staged.documents_generation
                prior_failure = await staging_session.scalar(
                    select(JobFailure).where(
                        JobFailure.job_type == "parse_documents", JobFailure.job_key == stable_key
                    )
                )
                if prior_failure is not None:
                    # Carry discovery retry attempts into their first staged generation.
                    prior_failure.payload_json = {
                        **prior_failure.payload_json,
                        "documents_generation": str(processing_generation),
                    }
                await staging_session.commit()
            host = (
                DOCUMENT_HOST
                if source_code == SOURCE_CODE
                else urlsplit(source_base_url).hostname
            )
            if host is None:
                raise MalformedJobError("source base URL has no host")
            async with _session_scope(ctx) as processing_session:
                processed += await persist_and_parse_attachments(
                    processing_session,
                    opportunity_version_id=version_id,
                    refs=refs,
                    allowed_source_host=host,
                    storage_root=storage_root,
                    max_bytes=settings.attachment_max_bytes,
                    ocr_adapter=ctx.get("ocr_adapter"),
                    processing_generation=processing_generation,
                )
                current = (
                    await processing_session.scalars(
                        select(OpportunityVersion)
                        .where(OpportunityVersion.id == version_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).one()
                if current.documents_generation == processing_generation:
                    await processing_session.execute(
                        update(JobFailure)
                        .where(
                            JobFailure.job_type == "parse_documents",
                            JobFailure.job_key == stable_key,
                        )
                        .values(attempts=0, dead_lettered=False, next_retry_at=None)
                    )
                await processing_session.commit()
        except Exception as error:
            async with _session_scope(ctx) as failure_session:
                current = (
                    await failure_session.scalars(
                        select(OpportunityVersion)
                        .where(OpportunityVersion.id == version_id)
                        .with_for_update()
                    )
                ).one()
                if current.documents_generation != processing_generation:
                    continue  # A late failing worker cannot overwrite a newer run's retry state.
                failure = await _record_failure(
                    failure_session,
                    job_type="parse_documents",
                    stable_key=stable_key,
                    payload={
                        "source_code": source_code,
                        "raw_record_id": str(raw_id),
                        "documents_generation": str(processing_generation)
                        if processing_generation
                        else None,
                    },
                    error=error,
                    dead_lettered=not _is_transient(error),
                )
                if failure.attempts >= MAX_ATTEMPTS:
                    failure.dead_lettered = True
                    failure.next_retry_at = None
                if failure.dead_lettered:
                    await complete_document_generation(
                        failure_session,
                        opportunity_version_id=version_id,
                        generation=processing_generation,
                        gaps={
                            "stage": "documents",
                            "status": "dead_lettered",
                            "job_key": stable_key,
                        },
                    )
                await failure_session.commit()
            failed += 1
    return {"processed": processed, "failed": failed}
