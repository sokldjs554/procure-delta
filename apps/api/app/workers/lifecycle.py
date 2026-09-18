from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from arq import Retry
from arq.connections import ArqRedis
from sqlalchemy import func, select, update

from app.lifecycle.linker import GRAPH_LOCK_ID, LinkCandidate, link_candidate
from app.models import JobFailure, LifecycleLink, Opportunity, OpportunityVersion
from app.workers.jobs import (
    MAX_ATTEMPTS,
    WORKER_QUEUE,
    _is_transient,
    _record_failure,
    _session_scope,
    job_key,
)


def _candidate(opportunity: Opportunity, version: OpportunityVersion) -> LinkCandidate:
    normalized = version.normalized_json
    source_id = UUID(str(normalized["source_id"]))
    references = tuple(
        (
            UUID(str(item.get("source_id", source_id))),
            str(item["source_record_id"]),
            str(item["lifecycle_stage"]),
        )
        for item in normalized.get("official_references", ())
    )
    identifiers = tuple(
        (str(item["scheme"]).casefold(), str(item["value"]).casefold())
        for item in normalized.get("normalized_identifiers", ())
    )
    amount = normalized.get("estimated_amount")
    published = normalized.get("published_at")
    return LinkCandidate(
        opportunity_id=opportunity.id,
        source_id=source_id,
        source_record_id=version.source_record_id,
        lifecycle_stage=str(opportunity.lifecycle_stage),
        title=opportunity.title,
        buyer_name=opportunity.buyer_name,
        estimated_amount=Decimal(str(amount)) if amount is not None else None,
        published_at=datetime.fromisoformat(str(published)) if published else None,
        official_references=references,
        normalized_identifiers=identifiers,
    )


async def _load_candidates(session: Any) -> list[LinkCandidate]:
    rows = (
        await session.execute(
            select(Opportunity, OpportunityVersion)
            .join(OpportunityVersion, Opportunity.current_version_id == OpportunityVersion.id)
            .order_by(Opportunity.id)
        )
    ).all()
    return [_candidate(opportunity, version) for opportunity, version in rows]


async def _acquire_graph_lock(session: Any) -> None:
    await session.execute(select(func.pg_advisory_xact_lock(GRAPH_LOCK_ID)))


async def link_opportunity(ctx: dict[str, Any], opportunity_id: str) -> dict[str, str]:
    stable_key = job_key("link_opportunity", "opportunity", {"opportunity_id": opportunity_id})
    async with _session_scope(ctx) as session:
        try:
            failure = await session.scalar(
                select(JobFailure).where(
                    JobFailure.job_type == "link_opportunity", JobFailure.job_key == stable_key
                )
            )
            if failure is not None and failure.attempts > 0:
                if failure.dead_lettered or failure.attempts >= MAX_ATTEMPTS:
                    return {"status": "dead_lettered", "job_key": stable_key}
                if failure.next_retry_at is not None and failure.next_retry_at > datetime.now(UTC):
                    return {"status": "deferred", "job_key": stable_key}
            identifier = UUID(opportunity_id)
            # Serialize graph revisions across workers; stage ordering then makes cycles impossible.
            await _acquire_graph_lock(session)
            decision_at = await session.scalar(select(func.clock_timestamp()))
            if decision_at is None:
                raise RuntimeError("database did not provide a lifecycle decision timestamp")
            # This row lock serializes competing decisions for one child across workers.
            child = await session.scalar(
                select(Opportunity).where(Opportunity.id == identifier).with_for_update()
            )
            if child is None or child.current_version_id is None:
                return {"status": "missing", "job_key": stable_key}
            version = await session.get_one(OpportunityVersion, child.current_version_id)
            record = _candidate(child, version)
            candidates = [
                item
                for item in await _load_candidates(session)
                if item.opportunity_id != identifier
            ]
            decision = link_candidate(record, candidates)
            if decision.status != "resolved" or decision.parent_opportunity_id is None:
                await session.execute(
                    update(LifecycleLink)
                    .where(
                        LifecycleLink.child_opportunity_id == identifier,
                        LifecycleLink.status == "active",
                    )
                    .values(status="retracted", retracted_at=decision_at)
                )
                await session.commit()
                return {
                    "status": "unresolved",
                    "job_key": stable_key,
                    "reason": decision.reason or "unknown",
                }
            parent = await session.get_one(Opportunity, decision.parent_opportunity_id)
            evidence = {
                **dict(decision.evidence or {}),
                "ruleset": "lifecycle-linker-v1",
                "parent_version_id": str(parent.current_version_id),
                "child_version_id": str(version.id),
            }
            existing_active = await session.scalar(
                select(LifecycleLink.id).where(
                    LifecycleLink.parent_opportunity_id == decision.parent_opportunity_id,
                    LifecycleLink.child_opportunity_id == identifier,
                    LifecycleLink.parent_version_id == parent.current_version_id,
                    LifecycleLink.child_version_id == version.id,
                    LifecycleLink.relation_type == "precedes",
                    LifecycleLink.status == "active",
                )
            )
            if existing_active is None:
                await session.execute(
                    update(LifecycleLink)
                    .where(
                        LifecycleLink.child_opportunity_id == identifier,
                        LifecycleLink.status == "active",
                    )
                    .values(status="retracted", retracted_at=decision_at)
                )
                session.add(
                    LifecycleLink(
                        parent_opportunity_id=decision.parent_opportunity_id,
                        child_opportunity_id=identifier,
                        parent_version_id=parent.current_version_id,
                        child_version_id=version.id,
                        relation_type="precedes",
                        confidence=decision.confidence,
                        evidence_json=evidence,
                        link_method=decision.method,
                        status="active",
                        created_at=decision_at,
                    )
                )
                await session.flush()
            await session.execute(
                update(JobFailure)
                .where(JobFailure.job_type == "link_opportunity", JobFailure.job_key == stable_key)
                .values(attempts=0, dead_lettered=False, next_retry_at=None)
            )
            await session.commit()
            return {
                "status": "existing" if existing_active is not None else "linked",
                "job_key": stable_key,
            }
        except Exception as error:
            # Only primitive identifiers survive rollback; loaded ORM instances may expire.
            await session.rollback()
            failure = await _record_failure(
                session,
                job_type="link_opportunity",
                stable_key=stable_key,
                payload={"opportunity_id": opportunity_id},
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


async def reconcile_lifecycle_links(ctx: dict[str, Any]) -> dict[str, int]:
    pending: list[tuple[str, str]] = []
    async with _session_scope(ctx) as session:
        ids = list(await session.scalars(select(Opportunity.id).order_by(Opportunity.id)))
        now = datetime.now(UTC)
        for opportunity_uuid in ids:
            stable_key = job_key(
                "link_opportunity", "opportunity", {"opportunity_id": str(opportunity_uuid)}
            )
            failure = await session.scalar(
                select(JobFailure).where(
                    JobFailure.job_type == "link_opportunity", JobFailure.job_key == stable_key
                )
            )
            if failure is not None and (
                failure.dead_lettered
                or failure.attempts >= MAX_ATTEMPTS
                or (failure.next_retry_at is not None and failure.next_retry_at > now)
            ):
                continue
            pending.append((str(opportunity_uuid), stable_key))

    linked = unresolved = 0
    redis = ctx.get("redis")
    for pending_id, stable_key in pending:
        if isinstance(redis, ArqRedis):
            await redis.enqueue_job(
                "link_opportunity",
                pending_id,
                _job_id=stable_key,
                _queue_name=WORKER_QUEUE,
            )
            continue
        try:
            outcome = await link_opportunity(ctx, pending_id)
            linked += outcome["status"] == "linked"
            unresolved += outcome["status"] == "unresolved"
        except Retry:
            continue
    return {"linked": linked, "unresolved": unresolved}
