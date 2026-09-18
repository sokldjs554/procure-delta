"""Real PostgreSQL seed/watch/delta/outcome contract; never counted as offline tests."""
from uuid import uuid4

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_phased_seed_is_idempotent_and_materializes_watched_delta(
    monkeypatch, worker_session_factory, tmp_path
):
    from app import db
    from app.config import get_settings
    from app.demo.seed import seed
    from app.models import (
        CompanyProfile,
        LifecycleLink,
        NotificationEvent,
        OpportunityVersion,
        Watchlist,
    )

    monkeypatch.setattr(db, 'SessionLocal', worker_session_factory)
    settings = get_settings()
    monkeypatch.setattr(settings, 'database_url', 'postgresql+psycopg://local@localhost/demo_test')
    monkeypatch.setattr(settings, 'attachment_storage_path', tmp_path)
    monkeypatch.setattr(settings, 'demo_auth_enabled', True)
    monkeypatch.setattr(settings, 'notification_external_enabled', False)
    monkeypatch.setattr(settings, 'extraction_mode', 'deterministic')
    run_id = 'seed-' + uuid4().hex[:12]
    base = await seed('base', run_id)
    tender = base['versions'][1]
    from uuid import UUID
    opportunity_id = UUID(tender['opportunity_id'])
    repeat = await seed('base', run_id)
    assert all(not row['new_raw'] for row in repeat['versions'])
    async with worker_session_factory() as session:
        owner = 'synthetic-e2e-' + run_id
        session.add(CompanyProfile(owner_user_id=owner, display_name='Synthetic fixture company',
            synthetic_demo=True, regions=['Seoul'], industries=['services'],
            capabilities=['cloud migration', 'document processing'], certifications=['ISO 27001'],
            contract_currency='KRW'))
        session.add(Watchlist(user_id=owner, opportunity_id=opportunity_id))
        await session.commit()
    await seed('amendment', run_id)
    await seed('outcome', run_id)
    async with worker_session_factory() as session:
        versions = list(await session.scalars(select(OpportunityVersion).where(
            OpportunityVersion.opportunity_id == opportunity_id)))
        assert len(versions) == 2
        notices = list(await session.scalars(select(NotificationEvent).where(
            NotificationEvent.user_id == owner)))
        assert any(
            n.template_key == 'watched_material_change' and n.status == 'sent'
            for n in notices
        )
        assert any(n.template_key == 'outcome_published' for n in notices)
        links = list(await session.scalars(select(LifecycleLink).where(
            LifecycleLink.status == 'active')))
        assert any(link.parent_opportunity_id == opportunity_id for link in links)
