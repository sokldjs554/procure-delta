"""Real PostgreSQL regression tests for bounded inbox metadata reads."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.api.opportunities import list_opportunities
from app.models import (
    CompanyProfile,
    EligibilityResult,
    Opportunity,
    OpportunityVersion,
    RankingResult,
    RawRecord,
    Watchlist,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 20])
async def test_inbox_metadata_select_count_does_not_grow_with_page_size(session, limit):
    # Reintroducing per-row watch/transition reads must exceed this bounded query budget.
    now = datetime.now(UTC)
    buyer = "batch-" + uuid4().hex
    rows = [
        Opportunity(
            canonical_key=f"{buyer}-{index}",
            title="Synthetic inbox query count",
            buyer_name=buyer,
            published_at=now - timedelta(seconds=index),
        )
        for index in range(25)
    ]
    session.add_all(rows)
    await session.flush()
    statements = []

    def record_select(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    connection = await session.connection()
    event.listen(connection.sync_connection, "before_cursor_execute", record_select)
    try:
        first = await list_opportunities(session, "owner-without-profile", limit=limit, buyer=buyer)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", record_select)

    assert [item.id for item in first.items] == [row.id for row in rows[:limit]]
    assert first.next_cursor is not None
    assert all(item.decision_status == "missing_version" for item in first.items)
    assert all(item.eligibility is None and item.ranking is None for item in first.items)
    # Profile + ordered page + owner-scoped watches + grouped current transitions.
    assert len(statements) <= 4, f"{limit}-item page issued {len(statements)} SELECTs"
    second = await list_opportunities(
        session, "owner-without-profile", limit=limit, buyer=buyer, cursor=first.next_cursor
    )
    assert [item.id for item in second.items] == [row.id for row in rows[limit : limit * 2]]
    assert not ({item.id for item in first.items} & {item.id for item in second.items})


@pytest.mark.asyncio
async def test_batched_metadata_preserves_owner_latest_current_transition_and_unknown(
    session, opportunities
):
    # Dropping owner/kind predicates, MAX, or null handling must change the returned values.
    owner = "batch-owner"
    session.add_all([
        Watchlist(user_id=owner, opportunity_id=opportunities[0].id),
        Watchlist(user_id="other-owner", opportunity_id=opportunities[1].id),
    ])
    original = await session.get_one(OpportunityVersion, opportunities[0].current_version_id)
    raw = await session.get_one(RawRecord, original.raw_record_id)
    latest = datetime(2026, 9, 25, 12, tzinfo=UTC)
    original.transition_kind = "current"
    original.transition_at = latest - timedelta(days=1)
    for number, kind, changed in [
        (2, "current", latest),
        (3, "historical", latest + timedelta(days=1)),
    ]:
        source_record_id = f"batch-{number}"
        next_raw = RawRecord(
            source_id=raw.source_id,
            source_record_id=source_record_id,
            payload_sha256=str(number) * 64,
            payload_json={},
        )
        session.add(next_raw)
        await session.flush()
        session.add(OpportunityVersion(
            opportunity_id=opportunities[0].id,
            raw_record_id=next_raw.id,
            version_number=number,
            source_record_id=source_record_id,
            normalized_sha256=str(number) * 64,
            normalized_json={},
            transition_kind=kind,
            transition_at=changed,
        ))
    await session.flush()
    page = await list_opportunities(session, owner, buyer=opportunities[0].buyer_name)
    values = {item.id: item for item in page.items}
    assert values[opportunities[0].id].watched is True
    assert values[opportunities[0].id].changed_at == latest
    assert values[opportunities[1].id].watched is False
    assert values[opportunities[1].id].changed_at is None
    assert all(item.decision_status == "profile_required" for item in page.items)


@pytest.mark.asyncio
async def test_unfiltered_lookahead_does_not_materialize_decisions_until_returned(
    session, opportunities
):
    # Summarizing limit+1 would create eligibility/ranking rows for an unseen next-page item.
    owner = "batch-profile-owner"
    session.add(CompanyProfile(owner_user_id=owner, display_name="Synthetic", synthetic_demo=True))
    await session.flush()
    first = await list_opportunities(session, owner, limit=2, buyer=opportunities[0].buyer_name)
    assert len(first.items) == 2 and first.next_cursor is not None
    assert all(item.eligibility is not None and item.ranking is not None for item in first.items)
    expected_versions = {item.current_version_id for item in first.items}
    assert set(await session.scalars(select(EligibilityResult.opportunity_version_id))) == (
        expected_versions
    )
    assert set(await session.scalars(select(RankingResult.opportunity_version_id))) == (
        expected_versions
    )
    second = await list_opportunities(
        session, owner, limit=2, buyer=opportunities[0].buyer_name, cursor=first.next_cursor
    )
    assert second.next_cursor is None
    assert {item.id for item in first.items + second.items} == {row.id for row in opportunities}
    assert all(item.eligibility is not None and item.ranking is not None for item in second.items)
