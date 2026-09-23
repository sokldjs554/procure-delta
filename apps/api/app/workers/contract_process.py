from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    ContractProcessSnapshot,
    Opportunity,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
)
from app.services.contract_process import (
    persist_contract_process_pages,
    query_for_service_record_id,
)
from app.sources.koneps import SOURCE_CODE
from app.sources.koneps_process import KonepsContractProcessClient

logger = logging.getLogger(__name__)


async def reconcile_contract_process(ctx: dict[str, Any]) -> dict[str, int]:
    settings = get_settings()
    if not settings.koneps_process_enabled:
        return {"lookups": 0, "snapshots": 0, "failed": 0, "skipped": 0}

    service_key = settings.koneps_service_key
    inquiry_div = (settings.koneps_process_inquiry_div or "").strip()
    if service_key is None or not service_key.get_secret_value().strip():
        raise ValueError("KONEPS_SERVICE_KEY is required for contract-process lookup")
    if not inquiry_div:
        raise ValueError("KONEPS_PROCESS_INQUIRY_DIV is required when lookup is enabled")

    factory = ctx.get("session_factory", SessionLocal)
    if not isinstance(factory, async_sessionmaker):
        raise TypeError("session_factory must be an async_sessionmaker")
    client = ctx.get("contract_process_client") or KonepsContractProcessClient(
        service_key=service_key.get_secret_value()
    )
    if not isinstance(client, KonepsContractProcessClient) and not hasattr(client, "fetch_all"):
        raise TypeError("contract_process_client must provide fetch_all")

    async with factory() as discovery:
        rows = (
            await discovery.execute(
                select(OpportunityVersion.id, OpportunityVersion.source_record_id)
                .join(Opportunity, Opportunity.current_version_id == OpportunityVersion.id)
                .join(RawRecord, RawRecord.id == OpportunityVersion.raw_record_id)
                .join(SourceRegistry, SourceRegistry.id == RawRecord.source_id)
                .where(SourceRegistry.code == SOURCE_CODE)
                .order_by(OpportunityVersion.created_at, OpportunityVersion.id)
                .limit(settings.koneps_process_batch_size)
            )
        ).all()

    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=settings.koneps_process_refresh_seconds)
    lookups = snapshots = failed = skipped = 0
    for version_id, source_record_id in rows:
        query = query_for_service_record_id(source_record_id, inquiry_div=inquiry_div)
        async with factory() as state:
            latest = await state.scalar(
                select(func.max(ContractProcessSnapshot.fetched_at)).where(
                    ContractProcessSnapshot.opportunity_version_id == version_id,
                    ContractProcessSnapshot.query_fingerprint == query.fingerprint(),
                )
            )
        if latest is not None and latest >= cutoff:
            skipped += 1
            continue
        try:
            pages = await client.fetch_all(
                query, max_pages=settings.koneps_process_max_pages
            )
            async with factory() as write_session:
                snapshots += await persist_contract_process_pages(
                    write_session,
                    opportunity_version_id=version_id,
                    query=query,
                    pages=pages,
                )
                await write_session.commit()
            lookups += 1
        except Exception as error:
            logger.warning(
                "contract_process_lookup_failed",
                extra={
                    "opportunity_version_id": str(version_id),
                    "error_class": type(error).__name__,
                },
            )
            failed += 1
    return {
        "lookups": lookups,
        "snapshots": snapshots,
        "failed": failed,
        "skipped": skipped,
    }
