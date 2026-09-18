"""CLI-only, append-only demo phases using the actual persistence/processing services."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url

from app.demo.dataset import demo_records


async def seed(phase: str, run_id: str) -> dict[str, Any]:
    from app.config import get_settings
    from app.db import SessionLocal
    from app.documents.service import persist_and_parse_attachments
    from app.extraction.deterministic import DeterministicExtractor
    from app.models import (
        IngestRun,
        NotificationEvent,
        OpportunityVersion,
        RawRecord,
        SourceRegistry,
    )
    from app.repositories.opportunities import upsert_opportunity_version
    from app.services.ingest import ingest_raw_record
    from app.services.normalize import normalize_raw_record
    from app.sources.base import AttachmentRef
    from app.workers.delta import compute_opportunity_delta
    from app.workers.extraction import extract_version
    from app.workers.lifecycle import reconcile_lifecycle_links
    from app.workers.notifications import deliver_notification, reconcile_notifications
    from app.workers.ranking import reconcile_ranking_results

    settings = get_settings()
    if not settings.demo_auth_enabled or make_url(settings.database_url).host not in {
        'postgres', 'localhost', '127.0.0.1', '::1'
    }:
        raise ValueError('demo seed requires local services with DEMO_AUTH_ENABLED=true')
    if settings.notification_external_enabled or settings.extraction_mode != 'deterministic':
        raise ValueError('demo seed requires local notification and deterministic extraction modes')
    code = 'lifecycle-demo-' + run_id
    anchor = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    from uuid import UUID
    demo_records(run_id, anchor, UUID(int=1))  # Validate arguments before writes.
    async with SessionLocal() as session:
        await session.execute(insert(SourceRegistry).values(
            code=code, display_name=f'Synthetic lifecycle demo [{run_id}]',
            base_url='https://example.invalid', enabled=False,
        ).on_conflict_do_nothing(index_elements=['code']))
        source = (await session.scalars(
            select(SourceRegistry).where(SourceRegistry.code == code)
        )).one()
        source_id = source.id
        prior = await session.scalar(select(RawRecord).where(
            RawRecord.source_id == source_id, RawRecord.source_record_id == f'{run_id}-prespec'
        ).order_by(RawRecord.fetched_at).limit(1))
        if prior is not None:
            anchor = datetime.fromisoformat(prior.payload_json['demo_anchor'])
            if phase == 'outcome':
                amendment = await session.scalar(select(RawRecord.id).where(
                    RawRecord.source_id == source_id,
                    RawRecord.source_record_id == f'{run_id}-tender',
                    RawRecord.payload_json['lifecycle_stage'].astext == 'amendment',
                ).limit(1))
                if amendment is None:
                    raise ValueError('run the amendment phase before outcomes')
        elif phase not in {'base', 'all'}:
            raise ValueError(
                'run the base phase first; a later phase must not silently invent its past'
            )
        await session.commit()
    indices = {'base': [0, 1], 'amendment': [2], 'outcome': [3, 4], 'all': list(range(5))}[phase]
    records = demo_records(run_id, anchor, source_id)
    processed = []
    ctx: dict[str, Any] = {'session_factory': SessionLocal, 'extractor': DeterministicExtractor()}
    for index in indices:
        record = records[index]
        async with SessionLocal() as session:
            outcome = await ingest_raw_record(session, source_id, record)
            await session.commit()  # Original bytes/envelope survive later processing failures.
            raw = await session.get_one(RawRecord, outcome.raw_record_id)
            normalized = normalize_raw_record(raw, source_code=code)
            version = await upsert_opportunity_version(session, raw, normalized)
            identifier = version.version_id
            opportunity_id = version.opportunity_id
            await session.commit()
            stored = await session.get_one(OpportunityVersion, identifier)
            if stored.documents_completed_at is None:
                await persist_and_parse_attachments(
                    session, opportunity_version_id=identifier,
                    refs=[
                        AttachmentRef.model_validate(ref)
                        for ref in record.raw_payload['attachments']
                    ],
                    allowed_source_host='example.invalid',
                        storage_root=settings.attachment_storage_path,
                )
                await session.commit()
        extraction = await extract_version(ctx, str(identifier))
        delta = await compute_opportunity_delta(ctx, str(identifier))
        if extraction['status'] != 'validated':
            raise RuntimeError('demo document did not produce a validated extraction')
        if delta['status'] == 'dead_lettered':
            raise RuntimeError('demo delta failed; inspect the local admin console')
        processed.append({'stage': record.raw_payload['lifecycle_stage'],
                          'opportunity_id': str(opportunity_id), 'version_id': str(identifier),
                          'new_raw': outcome.created, 'extraction': extraction['status'],
                          'delta': delta['status']})
    await reconcile_lifecycle_links(ctx)
    await reconcile_ranking_results(ctx)
    notifications = await reconcile_notifications(ctx)
    async with SessionLocal() as session:
        # Deliver only this demo's local outbox intents, never unrelated external notifications.
        from app.models import Opportunity
        ids = list(await session.scalars(select(NotificationEvent.id).join(
            Opportunity, NotificationEvent.opportunity_id == Opportunity.id
        ).join(OpportunityVersion, Opportunity.current_version_id == OpportunityVersion.id).join(
            RawRecord, OpportunityVersion.raw_record_id == RawRecord.id
        ).where(RawRecord.source_id == source_id, NotificationEvent.channel == 'local',
                NotificationEvent.status == 'pending')))
    delivered = [await deliver_notification(ctx, str(identifier)) for identifier in ids]
    async with SessionLocal() as session:
        source = await session.get_one(SourceRegistry, source_id)
        source.last_success_at = datetime.now(UTC)
        session.add(IngestRun(source_id=source_id, status='success', finished_at=datetime.now(UTC),
                              fetched_count=len(processed),
                                  created_count=sum(x['new_raw'] for x in processed),
                              duplicate_count=sum(not x['new_raw'] for x in processed),
                              updated_count=sum(
                                  x['new_raw'] and x['stage'] == 'amendment'
                                  for x in processed
                              ),
                              cursor_after=f'demo:{phase}'))
        await session.commit()
    return {'synthetic': True, 'run_id': run_id, 'phase': phase, 'anchor': anchor.isoformat(),
            'versions': processed, 'notification_reconcile': notifications,
            'local_delivery_statuses': [item['status'] for item in delivered],
            'external_api_calls': 0, 'real_ocr_performed': False}


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Append synthetic lifecycle phases to a local demo DB'
    )
    parser.add_argument('--phase', choices=['base', 'amendment', 'outcome', 'all'], required=True)
    parser.add_argument('--run-id', default='review')
    args = parser.parse_args()
    print(json.dumps(asyncio.run(seed(args.phase, args.run_id)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
