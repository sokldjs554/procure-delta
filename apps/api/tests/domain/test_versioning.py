from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Opportunity, OpportunityVersion, RawRecord, SourceRegistry
from app.repositories.opportunities import upsert_opportunity_version
from app.services.normalize import normalize_raw_record


async def _raw(
    session: AsyncSession,
    source: SourceRegistry,
    *,
    title: str,
    effective_at: datetime,
    checksum: str,
) -> RawRecord:
    raw = RawRecord(
        source_id=source.id,
        source_record_id="synthetic-tender-001",
        source_updated_at=effective_at,
        payload_json={
            "title": title,
            "buyer_name": "Synthetic Seoul Digital Agency",
            "lifecycle_stage": "tender",
            "status": "published",
            "is_synthetic": True,
        },
        payload_sha256=checksum,
    )
    session.add(raw)
    await session.flush()
    return raw


@pytest.mark.asyncio
async def test_identical_normalized_state_dedupes_and_marks_each_raw_processed(
    session: AsyncSession,
) -> None:
    source = SourceRegistry(code="mock-v", display_name="Mock", base_url="https://example.invalid")
    session.add(source)
    await session.flush()
    first_raw = await _raw(
        session,
        source,
        title="Synthetic tender",
        effective_at=datetime(2026, 9, 10, tzinfo=UTC),
        checksum="a" * 64,
    )
    second_raw = await _raw(
        session,
        source,
        title="Synthetic tender",
        effective_at=datetime(2026, 9, 11, tzinfo=UTC),
        checksum="b" * 64,
    )

    first = await upsert_opportunity_version(session, first_raw, normalize_raw_record(first_raw))
    second = await upsert_opportunity_version(session, second_raw, normalize_raw_record(second_raw))
    await session.flush()

    assert first.created is True
    assert second.created is False
    assert second.version_id == first.version_id
    assert await session.scalar(select(func.count()).select_from(OpportunityVersion)) == 1
    assert first_raw.normalization_status == "normalized"
    assert second_raw.normalization_status == "normalized"
    assert second_raw.normalized_version_id == first.version_id


@pytest.mark.asyncio
async def test_stale_replay_appends_observation_version_without_regressing_current(
    session: AsyncSession,
) -> None:
    source = SourceRegistry(
        code="mock-stale", display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    latest_raw = await _raw(
        session,
        source,
        title="Synthetic tender latest",
        effective_at=datetime(2026, 9, 12, tzinfo=UTC),
        checksum="c" * 64,
    )
    stale_raw = await _raw(
        session,
        source,
        title="Synthetic tender original",
        effective_at=datetime(2026, 9, 10, tzinfo=UTC),
        checksum="d" * 64,
    )

    latest = await upsert_opportunity_version(session, latest_raw, normalize_raw_record(latest_raw))
    stale = await upsert_opportunity_version(session, stale_raw, normalize_raw_record(stale_raw))
    await session.flush()

    versions = (
        await session.scalars(
            select(OpportunityVersion).order_by(OpportunityVersion.version_number)
        )
    ).all()
    opportunity = await session.get_one(Opportunity, latest.opportunity_id)
    assert [(version.version_number, version.source_record_id) for version in versions] == [
        (1, "synthetic-tender-001"),
        (2, "synthetic-tender-001"),
    ]
    assert versions[0].id == latest.version_id
    assert versions[1].id == stale.version_id
    assert opportunity.current_version_id == latest.version_id
    assert opportunity.title == "Synthetic tender latest"


@pytest.mark.asyncio
async def test_changed_payloads_append_consecutive_versions_and_advance_current(
    session: AsyncSession,
) -> None:
    source = SourceRegistry(
        code="mock-order", display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    first_raw = await _raw(
        session,
        source,
        title="Synthetic tender v1",
        effective_at=datetime(2026, 9, 10, tzinfo=UTC),
        checksum="1" * 64,
    )
    second_raw = await _raw(
        session,
        source,
        title="Synthetic tender v2",
        effective_at=datetime(2026, 9, 11, tzinfo=UTC),
        checksum="2" * 64,
    )

    first = await upsert_opportunity_version(session, first_raw, normalize_raw_record(first_raw))
    second = await upsert_opportunity_version(session, second_raw, normalize_raw_record(second_raw))
    opportunity = await session.get_one(Opportunity, first.opportunity_id)

    assert (first.version_number, second.version_number) == (1, 2)
    assert opportunity.current_version_id == second.version_id
    assert opportunity.title == "Synthetic tender v2"


@pytest.mark.asyncio
async def test_reversion_to_historical_state_creates_a_new_current_version(
    session: AsyncSession,
) -> None:
    source = SourceRegistry(
        code="mock-revert", display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    outcomes = []
    for index, title in enumerate(("State A", "State B", "State A"), start=1):
        raw = await _raw(
            session,
            source,
            title=title,
            effective_at=datetime(2026, 9, 9 + index, tzinfo=UTC),
            checksum=str(index) * 64,
        )
        outcomes.append(await upsert_opportunity_version(session, raw, normalize_raw_record(raw)))

    opportunity = await session.get_one(Opportunity, outcomes[0].opportunity_id)
    assert [outcome.version_number for outcome in outcomes] == [1, 2, 3]
    assert all(outcome.created for outcome in outcomes)
    assert opportunity.current_version_id == outcomes[2].version_id
    assert opportunity.title == "State A"


@pytest.mark.asyncio
async def test_equivalent_later_observation_advances_effective_watermark(
    session: AsyncSession,
) -> None:
    source = SourceRegistry(
        code="mock-watermark", display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    observations = [
        ("State A", datetime(2026, 9, 10, tzinfo=UTC), "4" * 64),
        ("State A", datetime(2026, 9, 12, tzinfo=UTC), "5" * 64),
        ("State B", datetime(2026, 9, 11, tzinfo=UTC), "6" * 64),
    ]
    outcomes = []
    for title, effective_at, checksum in observations:
        raw = await _raw(session, source, title=title, effective_at=effective_at, checksum=checksum)
        outcomes.append(await upsert_opportunity_version(session, raw, normalize_raw_record(raw)))

    opportunity = await session.get_one(Opportunity, outcomes[0].opportunity_id)
    assert [outcome.created for outcome in outcomes] == [True, False, True]
    assert opportunity.current_version_id == outcomes[0].version_id
    assert opportunity.current_effective_at == datetime(2026, 9, 12, tzinfo=UTC)
    assert opportunity.title == "State A"


@pytest.mark.asyncio
async def test_replaying_historical_raw_returns_its_existing_version(
    session: AsyncSession,
) -> None:
    source = SourceRegistry(
        code="mock-historical-replay", display_name="Mock", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    raw_a = await _raw(
        session,
        source,
        title="State A",
        effective_at=datetime(2026, 9, 10, tzinfo=UTC),
        checksum="7" * 64,
    )
    raw_b = await _raw(
        session,
        source,
        title="State B",
        effective_at=datetime(2026, 9, 11, tzinfo=UTC),
        checksum="8" * 64,
    )
    first = await upsert_opportunity_version(session, raw_a, normalize_raw_record(raw_a))
    await upsert_opportunity_version(session, raw_b, normalize_raw_record(raw_b))

    replay = await upsert_opportunity_version(session, raw_a, normalize_raw_record(raw_a))

    assert replay.created is False
    assert replay.version_id == first.version_id
    assert await session.scalar(select(func.count()).select_from(OpportunityVersion)) == 2


@pytest.mark.asyncio
async def test_stale_loaded_raw_refreshes_processed_identity_under_lock(
    worker_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with worker_session_factory() as setup:
        source = SourceRegistry(
            code="mock-stale-identity", display_name="Mock", base_url="https://example.invalid"
        )
        setup.add(source)
        await setup.flush()
        raw_a = await _raw(
            setup,
            source,
            title="State A",
            effective_at=datetime(2026, 9, 10, tzinfo=UTC),
            checksum="a1" * 32,
        )
        raw_b = await _raw(
            setup,
            source,
            title="State B",
            effective_at=datetime(2026, 9, 11, tzinfo=UTC),
            checksum="b2" * 32,
        )
        await setup.commit()
        raw_a_id, raw_b_id = raw_a.id, raw_b.id

    async with worker_session_factory() as stale_session:
        stale_raw_a = await stale_session.get_one(RawRecord, raw_a_id)
        async with worker_session_factory() as processing:
            current_a = await processing.get_one(RawRecord, raw_a_id)
            first = await upsert_opportunity_version(
                processing, current_a, normalize_raw_record(current_a)
            )
            current_b = await processing.get_one(RawRecord, raw_b_id)
            await upsert_opportunity_version(processing, current_b, normalize_raw_record(current_b))
            await processing.commit()

        replay = await upsert_opportunity_version(
            stale_session, stale_raw_a, normalize_raw_record(stale_raw_a)
        )
        await stale_session.commit()

    assert replay.created is False
    assert replay.version_id == first.version_id


@pytest.mark.asyncio
async def test_concurrent_same_version_creates_one_row(
    worker_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with worker_session_factory() as setup:
        source = SourceRegistry(
            code="mock-concurrent-version", display_name="Mock", base_url="https://example.invalid"
        )
        setup.add(source)
        await setup.commit()
        source_id = source.id
        raw_ids = []
        for checksum in ("e" * 64, "f" * 64):
            raw = await _raw(
                setup,
                source,
                title="Synthetic concurrent tender",
                effective_at=datetime(2026, 9, 10, tzinfo=UTC),
                checksum=checksum,
            )
            raw_ids.append(raw.id)
        await setup.commit()

    async def process(raw_id) -> object:  # type: ignore[no-untyped-def]
        async with worker_session_factory() as concurrent_session:
            raw = await concurrent_session.get_one(RawRecord, raw_id)
            outcome = await upsert_opportunity_version(
                concurrent_session, raw, normalize_raw_record(raw)
            )
            await concurrent_session.commit()
            return outcome

    await asyncio.gather(*(process(raw_id) for raw_id in raw_ids))

    async with worker_session_factory() as verify:
        canonical_key = normalize_raw_record(
            await verify.get_one(RawRecord, raw_ids[0])
        ).canonical_key
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.canonical_key == canonical_key)
            )
            == 1
        )
        opportunity = await verify.scalar(
            select(Opportunity).where(Opportunity.canonical_key == canonical_key)
        )
        assert opportunity is not None
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(OpportunityVersion)
                .where(OpportunityVersion.opportunity_id == opportunity.id)
            )
            == 1
        )
        await verify.execute(
            update(Opportunity)
            .where(Opportunity.id == opportunity.id)
            .values(current_version_id=None)
        )
        await verify.execute(
            update(RawRecord)
            .where(RawRecord.source_id == source_id)
            .values(normalized_version_id=None)
        )
        await verify.execute(
            delete(OpportunityVersion).where(OpportunityVersion.opportunity_id == opportunity.id)
        )
        await verify.execute(delete(RawRecord).where(RawRecord.source_id == source_id))
        await verify.execute(delete(Opportunity).where(Opportunity.id == opportunity.id))
        await verify.execute(delete(SourceRegistry).where(SourceRegistry.id == source_id))
        await verify.commit()
