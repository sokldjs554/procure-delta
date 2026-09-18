from __future__ import annotations

import re
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select

from app.api.auth import Operator, Redis, Session, rate_limit
from app.api.schemas import DTO
from app.models import (
    AuditEvent,
    DocumentParse,
    IngestRun,
    JobFailure,
    LocalNotificationReceipt,
    NotificationEvent,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
    StructuredExtraction,
)
from app.workers.jobs import WORKER_QUEUE

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class GroupCount(DTO):
    kind: str
    status: str
    count: int


class WorkerActivity(DTO):
    completed: int
    failed: int
    retried: int
    ongoing: int


def worker_activity(heartbeat: bytes | None) -> WorkerActivity | None:
    if heartbeat is None:
        return None
    fields = dict(
        re.findall(
            r"\bj_(complete|failed|retried|ongoing)=(\d+)\b",
            heartbeat.decode("utf-8", errors="replace"),
        )
    )
    if set(fields) != {"complete", "failed", "retried", "ongoing"}:
        return None
    return WorkerActivity(
        completed=int(fields["complete"]),
        failed=int(fields["failed"]),
        retried=int(fields["retried"]),
        ongoing=int(fields["ongoing"]),
    )


class Pipeline(DTO):
    observed_at: datetime
    records_fetched_today: int
    new_records_today: int
    changed_versions_today: int
    duplicates_skipped_today: int
    parsing_failures: int
    ocr_fallbacks: int
    structured_extraction_count: int
    schema_validation_failures: int
    retry_queue_count: int
    dlq_count: int
    worker_queue_depth: int
    scheduler_queue_depth: int
    worker_heartbeat: bool
    scheduler_heartbeat: bool
    worker_activity: WorkerActivity | None
    scheduler_activity: WorkerActivity | None
    parsing: list[GroupCount]
    extraction: list[GroupCount]


def pending_failure() -> Any:
    return or_(
        JobFailure.attempts > 0,
        JobFailure.dead_lettered.is_(True),
        JobFailure.next_retry_at.is_not(None),
    )


@router.get("/pipeline", response_model=Pipeline)
async def pipeline(session: Session, operator: Operator, redis: Redis) -> Pipeline:
    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    aggregates = (
        await session.execute(
            select(
                *[
                    func.coalesce(func.sum(column), 0)
                    for column in (
                        IngestRun.fetched_count,
                        IngestRun.created_count,
                        IngestRun.updated_count,
                        IngestRun.duplicate_count,
                    )
                ]
            ).where(IngestRun.started_at >= today)
        )
    ).one()
    parsing = [
        GroupCount(kind=kind, status=status, count=count)
        for kind, status, count in (
            await session.execute(
                select(DocumentParse.parser_kind, DocumentParse.status, func.count()).group_by(
                    DocumentParse.parser_kind, DocumentParse.status
                )
            )
        ).all()
    ]
    extraction = [
        GroupCount(kind=kind, status=status, count=count)
        for kind, status, count in (
            await session.execute(
                select(
                    StructuredExtraction.extractor_version,
                    StructuredExtraction.validation_status,
                    func.count(),
                ).group_by(
                    StructuredExtraction.extractor_version, StructuredExtraction.validation_status
                )
            )
        ).all()
    ]
    retries = await session.scalar(
        select(func.count())
        .select_from(JobFailure)
        .where(
            pending_failure(),
            JobFailure.dead_lettered.is_(False),
            JobFailure.next_retry_at.is_not(None),
        )
    )
    dlq = await session.scalar(
        select(func.count()).select_from(JobFailure).where(JobFailure.dead_lettered.is_(True))
    )
    return Pipeline(
        observed_at=now,
        records_fetched_today=int(aggregates[0]),
        new_records_today=int(aggregates[1]),
        changed_versions_today=int(aggregates[2]),
        duplicates_skipped_today=int(aggregates[3]),
        parsing_failures=sum(
            g.count for g in parsing if g.status in {"failed", "parse_failed", "unsupported"}
        ),
        ocr_fallbacks=sum(g.count for g in parsing if g.kind == "ocr"),
        structured_extraction_count=sum(g.count for g in extraction),
        schema_validation_failures=sum(g.count for g in extraction if g.status == "rejected"),
        retry_queue_count=int(retries or 0),
        dlq_count=int(dlq or 0),
        worker_queue_depth=await redis.zcard(WORKER_QUEUE),
        scheduler_queue_depth=await redis.zcard("arq:procure-delta:scheduler"),
        worker_heartbeat=bool(await redis.exists(WORKER_QUEUE + ":health-check")),
        scheduler_heartbeat=bool(await redis.exists("arq:procure-delta:scheduler:health-check")),
        worker_activity=worker_activity(await redis.get(WORKER_QUEUE + ":health-check")),
        scheduler_activity=worker_activity(
            await redis.get("arq:procure-delta:scheduler:health-check")
        ),
        parsing=parsing,
        extraction=extraction,
    )


class Source(DTO):
    id: UUID
    code: str
    display_name: str
    enabled: bool
    polling_interval_seconds: int
    last_success_at: datetime | None
    last_failure_at: datetime | None


@router.get("/sources", response_model=list[Source])
async def sources(session: Session, operator: Operator) -> list[Source]:
    return [
        Source.model_validate(row)
        for row in await session.scalars(select(SourceRegistry).order_by(SourceRegistry.code))
    ]


class Failure(DTO):
    id: UUID
    job_type: str
    attempts: int
    error_code: str
    last_error_at: datetime
    dead_lettered: bool
    next_retry_at: datetime | None


class FailurePage(DTO):
    items: list[Failure]
    next_cursor: str | None


SAFE_ERROR_CLASSES = {
    "TimeoutError",
    "ConnectTimeout",
    "ReadTimeout",
    "HTTPStatusError",
    "MalformedJobError",
    "ValidationError",
    "NotificationDeliveryError",
    "OperationalError",
    "ConnectionError",
}


@router.get("/failures", response_model=FailurePage)
async def failures(
    session: Session,
    operator: Operator,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
    dead_lettered: bool | None = None,
) -> FailurePage:
    statement = select(JobFailure).where(pending_failure())
    if cursor:
        statement = statement.where(JobFailure.id > cursor)
    if dead_lettered is not None:
        statement = statement.where(JobFailure.dead_lettered == dead_lettered)
    rows = list(await session.scalars(statement.order_by(JobFailure.id).limit(limit + 1)))
    return FailurePage(
        items=[
            Failure(
                id=row.id,
                job_type=row.job_type,
                attempts=row.attempts,
                error_code=row.error_class
                if row.error_class in SAFE_ERROR_CLASSES
                else "ProcessingError",
                last_error_at=row.last_error_at,
                dead_lettered=row.dead_lettered,
                next_retry_at=row.next_retry_at,
            )
            for row in rows[:limit]
        ],
        next_cursor=str(rows[limit - 1].id) if len(rows) > limit else None,
    )


class RetryResult(DTO):
    failure_id: UUID
    status: str
    queue_published: bool


@router.post("/failures/{identifier}/retry", response_model=RetryResult, status_code=202)
async def retry(
    identifier: UUID, session: Session, operator: Operator, redis: Redis
) -> RetryResult:
    await rate_limit(redis, "retry", operator.owner_id, 5)
    observed = await session.get(JobFailure, identifier)
    if observed is None:
        raise HTTPException(404, "Failure not found")
    # Match writer lock order: target event/version before its failure record.
    observed_payload = dict(observed.payload_json)
    try:
        if observed.job_type == "deliver_notification":
            await session.scalar(
                select(NotificationEvent)
                .where(NotificationEvent.id == UUID(observed_payload["notification_event_id"]))
                .with_for_update()
            )
        elif observed.job_type == "parse_documents":
            await session.scalar(
                select(OpportunityVersion)
                .where(OpportunityVersion.raw_record_id == UUID(observed_payload["raw_record_id"]))
                .with_for_update()
            )
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(409, "Retry input unavailable") from exc
    row = await session.scalar(
        select(JobFailure)
        .where(JobFailure.id == identifier)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "Failure not found")
    if not row.dead_lettered:
        raise HTTPException(409, "Only terminal failures can be manually retried")
    if row.payload_json != observed_payload:
        raise HTTPException(409, "Retry input changed; refresh failure")
    payload = row.payload_json
    args: list[Any] = []
    job = row.job_type
    try:
        if job == "deliver_notification":
            event = await session.scalar(
                select(NotificationEvent)
                .where(NotificationEvent.id == UUID(payload["notification_event_id"]))
                .with_for_update()
            )
            if event is None or event.dedupe_key != row.job_key or event.status != "dead_lettered":
                raise HTTPException(409, "Notification is not retryable")
            receipt = await session.scalar(
                select(LocalNotificationReceipt.id).where(
                    LocalNotificationReceipt.notification_event_id == event.id
                )
            )
            if event.sent_at is not None or receipt is not None:
                raise HTTPException(409, "Delivered notification cannot be retried")
            event.status, event.attempt_count = "pending", 0
            event.lease_token = None
            event.next_attempt_at = datetime.now(UTC)
            args = [str(event.id)]
        elif job in {"normalize_record", "parse_documents"}:
            raw = await session.get(RawRecord, UUID(payload["raw_record_id"]))
            if raw is None:
                raise HTTPException(409, "Retry input unavailable")
            if job == "normalize_record":
                raw.normalization_status = "pending"
                job = "reconcile_pending_normalizations"
            else:
                version = await session.scalar(
                    select(OpportunityVersion)
                    .where(OpportunityVersion.raw_record_id == raw.id)
                    .with_for_update()
                )
                if version is None:
                    raise HTTPException(409, "Retry version unavailable")
                version.documents_generation = uuid4()
                version.documents_completed_at = None
                version.document_gaps_json = {}
                job = "reconcile_pending_documents"
        elif job == "poll_source":
            args = [str(payload["source_code"])]
        elif job == "ingest_record":
            args = [
                str(payload["source_code"]),
                {k: v for k, v in payload.items() if k not in {"source_code", "raw_record_id"}},
            ]
        elif job == "extract_version":
            args = [str(UUID(payload["version_id"])), payload.get("expected_key")]
        elif job == "link_opportunity":
            args = [str(UUID(payload["opportunity_id"]))]
        elif job == "compute_opportunity_delta":
            args = [str(UUID(payload["to_version_id"]))]
        else:
            raise HTTPException(409, "Unsupported retry job")
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(409, "Retry input unavailable") from exc
    row.attempts, row.dead_lettered, row.next_retry_at = 0, False, datetime.now(UTC)
    audit = AuditEvent(
        actor_type="demo_operator",
        actor_id=operator.owner_id,
        action="retry_failure",
        entity_type="job_failure",
        entity_id=row.id,
        metadata_json={"job_type": row.job_type},
    )
    session.add(audit)
    await session.flush()
    retry_job_id = f"admin-retry:{row.id}:{audit.id}"
    await session.commit()  # Durable recovery state precedes queue publication.
    published = False
    with suppress(RedisError):
        published = (
            await redis.enqueue_job(job, *args, _job_id=retry_job_id, _queue_name=WORKER_QUEUE)
            is not None
        )
    return RetryResult(failure_id=identifier, status="retry_pending", queue_published=published)
