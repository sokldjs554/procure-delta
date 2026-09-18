from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from app.models import NotificationEvent, Opportunity, OpportunityVersion, RawRecord, SourceRegistry

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://procure_delta:procure_delta@localhost:5432/procure_delta_task4_test",
)
API_ROOT = Path(__file__).parents[2]


def assert_constraint(error: IntegrityError, expected: str) -> None:
    assert error.orig.diag.constraint_name == expected


def test_initial_migration_round_trips_from_base() -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.attributes["database_url"] = TEST_DATABASE_URL

    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.mark.asyncio
async def test_raw_record_checksum_is_unique_per_source_record(session: AsyncSession) -> None:
    source = SourceRegistry(
        code="mock", display_name="Mock source", base_url="https://example.test"
    )
    session.add(source)
    await session.commit()
    session.add(
        RawRecord(source_id=source.id, source_record_id="notice-1", payload_sha256="a" * 64)
    )
    await session.commit()
    session.add(
        RawRecord(source_id=source.id, source_record_id="notice-1", payload_sha256="a" * 64)
    )

    with pytest.raises(IntegrityError) as caught:
        await session.commit()

    assert_constraint(caught.value, "uq_raw_record_payload")


@pytest.mark.asyncio
async def test_opportunity_canonical_key_is_unique(session: AsyncSession) -> None:
    session.add(Opportunity(canonical_key="notice-1", title="First", buyer_name="Buyer"))
    await session.commit()
    session.add(Opportunity(canonical_key="notice-1", title="Duplicate", buyer_name="Buyer"))

    with pytest.raises(IntegrityError) as caught:
        await session.commit()

    assert_constraint(caught.value, "opportunities_canonical_key_key")


@pytest.mark.asyncio
async def test_opportunity_version_number_is_unique_for_an_opportunity(
    session: AsyncSession,
) -> None:
    source = SourceRegistry(
        code="version-unique", display_name="Mock source", base_url="https://example.test"
    )
    opportunity = Opportunity(canonical_key="notice-1", title="Notice", buyer_name="Buyer")
    session.add_all([source, opportunity])
    await session.commit()
    first_raw = RawRecord(
        source_id=source.id, source_record_id="notice-1", payload_sha256="1" * 64
    )
    second_raw = RawRecord(
        source_id=source.id, source_record_id="notice-2", payload_sha256="2" * 64
    )
    session.add_all([first_raw, second_raw])
    await session.commit()
    session.add(
        OpportunityVersion(
            opportunity_id=opportunity.id,
            raw_record_id=first_raw.id,
            version_number=1,
            source_record_id="notice-1",
            normalized_sha256="b" * 64,
        )
    )
    await session.commit()
    session.add(
        OpportunityVersion(
            opportunity_id=opportunity.id,
            raw_record_id=second_raw.id,
            version_number=1,
            source_record_id="notice-2",
            normalized_sha256="c" * 64,
        )
    )

    with pytest.raises(IntegrityError) as caught:
        await session.commit()

    assert_constraint(caught.value, "uq_opportunity_version_number")


@pytest.mark.asyncio
async def test_notification_dedupe_key_is_unique(session: AsyncSession) -> None:
    opportunity = Opportunity(canonical_key="notice-1", title="Notice", buyer_name="Buyer")
    session.add(opportunity)
    await session.commit()
    session.add(
        NotificationEvent(
            user_id="user-1",
            opportunity_id=opportunity.id,
            channel="local",
            template_key="new-opportunity",
            dedupe_key="notice-1:user-1",
        )
    )
    await session.commit()
    session.add(
        NotificationEvent(
            user_id="user-2",
            opportunity_id=opportunity.id,
            channel="local",
            template_key="new-opportunity",
            dedupe_key="notice-1:user-1",
        )
    )

    with pytest.raises(IntegrityError) as caught:
        await session.commit()

    assert_constraint(caught.value, "notification_events_dedupe_key_key")


@pytest.mark.asyncio
async def test_current_version_must_belong_to_its_opportunity(session: AsyncSession) -> None:
    source = SourceRegistry(
        code="current-owner", display_name="Mock source", base_url="https://example.test"
    )
    first = Opportunity(canonical_key="notice-1", title="First", buyer_name="Buyer")
    second = Opportunity(canonical_key="notice-2", title="Second", buyer_name="Buyer")
    session.add_all([source, first, second])
    await session.commit()
    raw = RawRecord(
        source_id=source.id, source_record_id="notice-1", payload_sha256="3" * 64
    )
    session.add(raw)
    await session.commit()
    first_version = OpportunityVersion(
        opportunity_id=first.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id="notice-1",
        normalized_sha256="b" * 64,
    )
    session.add(first_version)
    await session.commit()
    first.current_version_id = first_version.id
    await session.commit()

    second.current_version_id = first_version.id
    with pytest.raises(IntegrityError) as caught:
        await session.commit()

    assert_constraint(caught.value, "fk_opportunity_current_version")
