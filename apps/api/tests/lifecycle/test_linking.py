from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.workers.lifecycle as lifecycle_worker
from app.lifecycle.linker import GRAPH_LOCK_ID, LinkCandidate, LinkDecision, link_candidate
from app.models import (
    JobFailure,
    LifecycleLink,
    Opportunity,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
)
from app.repositories.opportunities import upsert_opportunity_version
from app.services.normalize import normalize_raw_record
from app.sources.mock import MockSourceAdapter
from app.workers.lifecycle import link_opportunity, reconcile_lifecycle_links

SOURCE = UUID("11111111-1111-1111-1111-111111111111")


@pytest_asyncio.fixture
async def clean_committed_lifecycle_fixtures(
    worker_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    yield
    async with worker_session_factory() as session:
        source_ids = list(
            await session.scalars(
                select(SourceRegistry.id).where(
                    or_(
                        SourceRegistry.code == "mock-lifecycle-linking",
                        SourceRegistry.code.like("immutable-link-%"),
                        SourceRegistry.code.like("cycle-link-%"),
                        SourceRegistry.code.like("locktime-link-%"),
                    )
                )
            )
        )
        if not source_ids:
            return
        raw_ids = list(
            await session.scalars(select(RawRecord.id).where(RawRecord.source_id.in_(source_ids)))
        )
        opportunity_ids = list(
            await session.scalars(
                select(OpportunityVersion.opportunity_id).where(
                    OpportunityVersion.raw_record_id.in_(raw_ids)
                )
            )
        )
        if opportunity_ids:
            await session.execute(
                delete(JobFailure).where(
                    JobFailure.job_type == "link_opportunity",
                    JobFailure.payload_json["opportunity_id"].astext.in_(
                        [str(value) for value in opportunity_ids]
                    ),
                )
            )
            await session.execute(
                delete(LifecycleLink).where(
                    or_(
                        LifecycleLink.parent_opportunity_id.in_(opportunity_ids),
                        LifecycleLink.child_opportunity_id.in_(opportunity_ids),
                    )
                )
            )
            await session.execute(
                update(Opportunity)
                .where(Opportunity.id.in_(opportunity_ids))
                .values(current_version_id=None)
            )
        if raw_ids:
            await session.execute(
                update(RawRecord)
                .where(RawRecord.id.in_(raw_ids))
                .values(normalized_version_id=None)
            )
            await session.execute(
                delete(OpportunityVersion).where(OpportunityVersion.raw_record_id.in_(raw_ids))
            )
        if opportunity_ids:
            await session.execute(delete(Opportunity).where(Opportunity.id.in_(opportunity_ids)))
        await session.execute(delete(RawRecord).where(RawRecord.source_id.in_(source_ids)))
        await session.execute(delete(SourceRegistry).where(SourceRegistry.id.in_(source_ids)))
        await session.commit()


def candidate(
    record_id: str,
    stage: str,
    *,
    source_id: UUID = SOURCE,
    title: str = "Synthetic cloud migration",
    references: tuple[tuple[UUID, str, str], ...] = (),
    identifiers: tuple[tuple[str, str], ...] = (),
) -> LinkCandidate:
    return LinkCandidate(
        opportunity_id=uuid4(),
        source_id=source_id,
        source_record_id=record_id,
        lifecycle_stage=stage,
        title=title,
        buyer_name="Synthetic Seoul Digital Agency",
        estimated_amount=Decimal("125000000"),
        published_at=datetime(2026, 9, 3, tzinfo=UTC),
        official_references=references,
        normalized_identifiers=identifiers,
    )


def test_official_upstream_reference_beats_heuristic_similarity() -> None:
    heuristic = candidate("similar", "tender")
    official = candidate("official", "tender", title="Unrelated title")
    record = candidate(
        "award",
        "award",
        references=((SOURCE, "official", "tender"),),
    )

    decision = link_candidate(record, [heuristic, official])

    assert decision == LinkDecision.resolved(
        official.opportunity_id,
        method="official_reference",
        confidence=Decimal("1.0000"),
        evidence={"source_id": str(SOURCE), "source_record_id": "official"},
    )


def test_exact_source_scoped_identifier_beats_fuzzy_title_date_match() -> None:
    exact = candidate("exact", "tender", identifiers=(("tender_number", "T-001"),))
    fuzzy = candidate("fuzzy", "tender")
    record = candidate("amendment", "amendment", identifiers=(("tender_number", "T-001"),))

    assert link_candidate(record, [fuzzy, exact]).parent_opportunity_id == exact.opportunity_id
    assert link_candidate(record, [fuzzy, exact]).method == "normalized_identifier"


def test_same_identifier_from_another_source_does_not_link() -> None:
    other = candidate(
        "same-id",
        "tender",
        source_id=UUID("22222222-2222-2222-2222-222222222222"),
        identifiers=(("tender_number", "T-001"),),
        title="Different procurement",
    )
    record = candidate("child", "amendment", identifiers=(("tender_number", "T-001"),))

    assert link_candidate(record, [other]).status == "unresolved"


def test_ambiguous_heuristic_match_is_unresolved_independent_of_order() -> None:
    first = candidate("first", "tender")
    second = candidate("second", "tender")
    record = candidate("award", "award")

    forward = link_candidate(record, [first, second])
    backward = link_candidate(record, [second, first])

    assert forward.status == backward.status == "unresolved"
    assert forward.reason == backward.reason == "ambiguous_fingerprint"
    assert forward.parent_opportunity_id is None


def test_heuristic_matches_across_multiple_compatible_stages_are_unresolved() -> None:
    tender = candidate("tender", "tender")
    amendment = candidate("amendment", "amendment")
    record = candidate("award", "award")

    decision = link_candidate(record, [tender, amendment])

    assert decision.status == "unresolved"
    assert decision.reason == "ambiguous_fingerprint"


def test_fingerprint_requires_known_amount_and_date_within_bounded_window() -> None:
    close = candidate("close", "tender", title="Synthetic cloud migrations")
    record = candidate("award", "award")
    assert link_candidate(record, [close]).method == "fingerprint"

    unknown = LinkCandidate(
        **{**close.__dict__, "opportunity_id": uuid4(), "estimated_amount": None}
    )
    child_unknown = LinkCandidate(
        **{**record.__dict__, "opportunity_id": uuid4(), "estimated_amount": None}
    )
    assert link_candidate(child_unknown, [unknown]).reason == "no_conservative_match"


def test_semantic_comparison_is_candidate_bounded_and_rejects_nonfinite_scores() -> None:
    calls = 0

    class Comparator:
        def compare(self, record: LinkCandidate, value: LinkCandidate) -> Decimal:
            nonlocal calls
            calls += 1
            return Decimal("NaN")

    record = candidate("contract", "contract", title="unmatched")
    values = [candidate(str(index), "tender", title=f"other {index}") for index in range(30)]
    assert link_candidate(record, values, semantic_comparator=Comparator()).status == "unresolved"
    assert calls == 20


def test_contradictory_official_references_and_backward_edges_are_unresolved() -> None:
    tender = candidate("tender", "tender")
    other = candidate("other", "tender")
    contradictory = candidate(
        "award",
        "award",
        references=((SOURCE, "tender", "tender"), (SOURCE, "other", "tender")),
    )
    backwards = candidate("pre", "pre-specification", references=((SOURCE, "tender", "tender"),))

    assert link_candidate(contradictory, [tender, other]).reason == "ambiguous_official_reference"
    assert link_candidate(backwards, [tender]).reason == "incompatible_stage"


@pytest.mark.asyncio
async def test_model_and_database_timestamp_defaults_match(
    session: AsyncSession,
) -> None:
    version_default = str(OpportunityVersion.__table__.c.created_at.server_default.arg)
    link_default = str(LifecycleLink.__table__.c.created_at.server_default.arg)
    rows = (
        await session.execute(
            text(
                """
                SELECT c.relname, pg_get_expr(d.adbin, d.adrelid) AS default_expression
                FROM pg_class AS c
                JOIN pg_attribute AS a ON a.attrelid = c.oid
                JOIN pg_attrdef AS d ON d.adrelid = c.oid AND d.adnum = a.attnum
                WHERE c.relname IN ('opportunity_versions', 'lifecycle_links')
                  AND a.attname = 'created_at'
                """
            )
        )
    ).all()
    database_defaults = {table: expression for table, expression in rows}

    assert version_default == "now()"
    assert database_defaults["opportunity_versions"] == "now()"
    assert link_default == "clock_timestamp()"
    assert database_defaults["lifecycle_links"] == "clock_timestamp()"


@pytest.mark.asyncio
async def test_reconciliation_persists_and_replays_default_demo_chain(
    worker_session_factory: async_sessionmaker[AsyncSession],
    clean_committed_lifecycle_fixtures: None,
) -> None:
    async with worker_session_factory() as session:
        source = SourceRegistry(
            code="mock-lifecycle-linking",
            display_name="Synthetic mock",
            base_url="https://example.invalid",
        )
        session.add(source)
        await session.flush()
        adapter = MockSourceAdapter(page_size=20)
        page = await adapter.discover(None)
        for sequence, value in enumerate(page.records):
            raw = RawRecord(
                source_id=source.id,
                source_record_id=value.source_record_id,
                source_updated_at=datetime(2026, 9, sequence + 1, tzinfo=UTC),
                payload_json=value.raw_payload,
                payload_sha256=f"{sequence + 1:064x}",
                schema_version="1",
            )
            session.add(raw)
            await session.flush()
            await upsert_opportunity_version(session, raw, normalize_raw_record(raw))
        await session.commit()

    ctx = {"session_factory": worker_session_factory}
    first = await reconcile_lifecycle_links(ctx)
    async with worker_session_factory() as session:
        seeded_ids = set(
            await session.scalars(
                select(Opportunity.id)
                .join(OpportunityVersion, Opportunity.current_version_id == OpportunityVersion.id)
                .where(OpportunityVersion.normalized_json["source_id"].astext == str(source.id))
            )
        )
        ids_before = set(
            await session.scalars(
                select(LifecycleLink.id).where(LifecycleLink.child_opportunity_id.in_(seeded_ids))
            )
        )
        links = list(
            await session.scalars(
                select(LifecycleLink).where(LifecycleLink.child_opportunity_id.in_(seeded_ids))
            )
        )
        stages = {
            row.id: row.lifecycle_stage
            for row in await session.scalars(
                select(Opportunity).where(Opportunity.id.in_(seeded_ids))
            )
        }
        assert {
            (stages[link.parent_opportunity_id], stages[link.child_opportunity_id])
            for link in links
        } == {
            ("pre-specification", "tender"),
            ("tender", "amendment"),
            ("amendment", "award"),
            ("award", "contract"),
        }
        assert all(link.link_method == "official_reference" for link in links)
        assert all(link.evidence_json["source_record_id"] for link in links)
        version_count = await session.scalar(
            select(func.count())
            .select_from(OpportunityVersion)
            .where(OpportunityVersion.normalized_json["source_id"].astext == str(source.id))
        )
        assert version_count == 6

    second = await reconcile_lifecycle_links(ctx)
    async with worker_session_factory() as session:
        assert (
            set(
                await session.scalars(
                    select(LifecycleLink.id).where(
                        LifecycleLink.child_opportunity_id.in_(seeded_ids)
                    )
                )
            )
            == ids_before
        )
    assert first["linked"] >= 4
    assert first["unresolved"] >= 1
    assert second["linked"] == 0
    assert second["unresolved"] >= 1

    async with worker_session_factory() as session:
        pre_spec = await session.scalar(
            select(Opportunity).where(
                Opportunity.id.in_(seeded_ids),
                Opportunity.lifecycle_stage == "pre-specification",
            )
        )
        assert pre_spec is not None
        pre_spec.lifecycle_stage = "contract"
        await session.commit()
    await reconcile_lifecycle_links(ctx)
    async with worker_session_factory() as session:
        active = list(
            await session.scalars(
                select(LifecycleLink).where(
                    LifecycleLink.child_opportunity_id.in_(seeded_ids),
                    LifecycleLink.status == "active",
                )
            )
        )
        current_stages = {
            row.id: row.lifecycle_stage
            for row in await session.scalars(
                select(Opportunity).where(Opportunity.id.in_(seeded_ids))
            )
        }
        ranks = {
            "pre-specification": 0,
            "tender": 1,
            "amendment": 2,
            "award": 3,
            "contract": 4,
        }
        assert all(
            ranks[str(current_stages[link.parent_opportunity_id])]
            < ranks[str(current_stages[link.child_opportunity_id])]
            for link in active
        )
        assert await session.scalar(
            select(func.count())
            .select_from(LifecycleLink)
            .where(
                LifecycleLink.child_opportunity_id.in_(seeded_ids),
                LifecycleLink.status == "retracted",
            )
        )


@pytest.mark.asyncio
async def test_parent_version_change_creates_immutable_link_revision(
    worker_session_factory: async_sessionmaker[AsyncSession],
    clean_committed_lifecycle_fixtures: None,
) -> None:
    async with worker_session_factory() as session:
        source = SourceRegistry(
            code=f"immutable-link-{uuid4()}",
            display_name="Synthetic immutable link",
            base_url="https://example.invalid",
        )
        session.add(source)
        await session.flush()
        records = (
            ("parent", "tender", (), "Synthetic immutable procurement"),
            (
                "child",
                "award",
                ({"source_record_id": "parent", "lifecycle_stage": "tender"},),
                "Synthetic immutable procurement award",
            ),
        )
        opportunities: dict[str, UUID] = {}
        for sequence, (record_id, stage, references, title) in enumerate(records):
            raw = RawRecord(
                source_id=source.id,
                source_record_id=record_id,
                source_updated_at=datetime(2026, 10, sequence + 1, tzinfo=UTC),
                payload_json={
                    "title": title,
                    "buyer_name": "Synthetic buyer",
                    "lifecycle_stage": stage,
                    "official_references": list(references),
                    "is_synthetic": True,
                },
                payload_sha256=f"{sequence + 50:064x}",
                schema_version="1",
            )
            session.add(raw)
            await session.flush()
            outcome = await upsert_opportunity_version(session, raw, normalize_raw_record(raw))
            opportunities[record_id] = outcome.opportunity_id
        await session.commit()

    ctx = {"session_factory": worker_session_factory}
    await link_opportunity(ctx, str(opportunities["child"]))
    async with worker_session_factory() as session:
        original = await session.scalar(
            select(LifecycleLink).where(
                LifecycleLink.child_opportunity_id == opportunities["child"],
                LifecycleLink.status == "active",
            )
        )
        assert original is not None
        original_id = original.id
        original_evidence = dict(original.evidence_json)
        raw = RawRecord(
            source_id=source.id,
            source_record_id="parent",
            source_updated_at=datetime(2026, 10, 10, tzinfo=UTC),
            payload_json={
                "title": "Synthetic immutable procurement corrected",
                "buyer_name": "Synthetic buyer",
                "lifecycle_stage": "tender",
                "revision": 2,
                "is_synthetic": True,
            },
            payload_sha256="9" * 64,
            schema_version="1",
        )
        session.add(raw)
        await session.flush()
        await upsert_opportunity_version(session, raw, normalize_raw_record(raw))
        await session.commit()

    await link_opportunity(ctx, str(opportunities["child"]))
    async with worker_session_factory() as session:
        revisions = list(
            await session.scalars(
                select(LifecycleLink)
                .where(LifecycleLink.child_opportunity_id == opportunities["child"])
                .order_by(LifecycleLink.id)
            )
        )
        assert len(revisions) == 2
        old = next(row for row in revisions if row.id == original_id)
        current = next(row for row in revisions if row.status == "active")
        assert old.status == "retracted"
        assert old.evidence_json == original_evidence
        assert current.id != old.id
        assert current.parent_version_id != old.parent_version_id
        assert old.created_at is not None
        assert current.created_at is not None
        assert old.created_at <= current.created_at


@pytest.mark.asyncio
async def test_stage_change_retracts_incident_edge_before_reverse_link(
    worker_session_factory: async_sessionmaker[AsyncSession],
    clean_committed_lifecycle_fixtures: None,
) -> None:
    async with worker_session_factory() as session:
        source = SourceRegistry(
            code=f"cycle-link-{uuid4()}",
            display_name="Synthetic cycle regression",
            base_url="https://example.invalid",
        )
        session.add(source)
        await session.flush()
        ids: dict[str, UUID] = {}
        for sequence, (record_id, stage, references) in enumerate(
            (
                ("a", "tender", ()),
                ("b", "award", ({"source_record_id": "a", "lifecycle_stage": "tender"},)),
            )
        ):
            raw = RawRecord(
                source_id=source.id,
                source_record_id=record_id,
                source_updated_at=datetime(2026, 11, sequence + 1, tzinfo=UTC),
                payload_json={
                    "title": f"Synthetic cycle {record_id}",
                    "buyer_name": "Synthetic buyer",
                    "lifecycle_stage": stage,
                    "official_references": list(references),
                    "is_synthetic": True,
                },
                payload_sha256=f"{sequence + 70:064x}",
                schema_version="1",
            )
            session.add(raw)
            await session.flush()
            outcome = await upsert_opportunity_version(session, raw, normalize_raw_record(raw))
            ids[record_id] = outcome.opportunity_id
        await session.commit()

    ctx = {"session_factory": worker_session_factory}
    await link_opportunity(ctx, str(ids["b"]))
    async with worker_session_factory() as session:
        changed = RawRecord(
            source_id=source.id,
            source_record_id="a",
            source_updated_at=datetime(2026, 11, 10, tzinfo=UTC),
            payload_json={
                "title": "Synthetic cycle a contract",
                "buyer_name": "Synthetic buyer",
                "lifecycle_stage": "contract",
                "official_references": [{"source_record_id": "b", "lifecycle_stage": "award"}],
                "is_synthetic": True,
            },
            payload_sha256="8" * 64,
            schema_version="1",
        )
        session.add(changed)
        await session.flush()
        await upsert_opportunity_version(session, changed, normalize_raw_record(changed))
        await session.commit()

    await link_opportunity(ctx, str(ids["a"]))
    async with worker_session_factory() as session:
        active = list(
            await session.scalars(
                select(LifecycleLink).where(
                    LifecycleLink.status == "active",
                    LifecycleLink.parent_opportunity_id.in_(ids.values()),
                    LifecycleLink.child_opportunity_id.in_(ids.values()),
                )
            )
        )
        assert [(row.parent_opportunity_id, row.child_opportunity_id) for row in active] == [
            (ids["b"], ids["a"])
        ]


@pytest.mark.asyncio
async def test_link_observation_time_is_after_actual_graph_lock_wait(
    worker_session_factory: async_sessionmaker[AsyncSession],
    clean_committed_lifecycle_fixtures: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with worker_session_factory() as session:
        source = SourceRegistry(
            code=f"locktime-link-{uuid4()}",
            display_name="Synthetic lock timestamp regression",
            base_url="https://example.invalid",
        )
        session.add(source)
        await session.flush()
        ids: dict[str, UUID] = {}
        for sequence, (record_id, stage, references) in enumerate(
            (
                ("parent", "tender", ()),
                (
                    "child",
                    "award",
                    ({"source_record_id": "parent", "lifecycle_stage": "tender"},),
                ),
            )
        ):
            raw = RawRecord(
                source_id=source.id,
                source_record_id=record_id,
                source_updated_at=datetime(2026, 12, sequence + 1, tzinfo=UTC),
                payload_json={
                    "title": f"Synthetic lock timestamp {record_id}",
                    "buyer_name": "Synthetic buyer",
                    "lifecycle_stage": stage,
                    "official_references": list(references),
                    "is_synthetic": True,
                },
                payload_sha256=f"{sequence + 90:064x}",
                schema_version="1",
            )
            session.add(raw)
            await session.flush()
            outcome = await upsert_opportunity_version(session, raw, normalize_raw_record(raw))
            ids[record_id] = outcome.opportunity_id
        await session.commit()

    ctx = {"session_factory": worker_session_factory}
    async with worker_session_factory() as session:
        child = await session.get_one(Opportunity, ids["child"])
        parent = await session.get_one(Opportunity, ids["parent"])
        stale = LifecycleLink(
            parent_opportunity_id=parent.id,
            child_opportunity_id=child.id,
            parent_version_id=None,
            child_version_id=child.current_version_id,
            relation_type="precedes",
            confidence=Decimal("0.5000"),
            evidence_json={"ruleset": "legacy-test"},
            link_method="legacy-test",
            status="active",
        )
        session.add(stale)
        await session.commit()
        stale_id = stale.id

    entering_lock = asyncio.Event()
    acquire_graph_lock = lifecycle_worker._acquire_graph_lock

    async def observed_lock_wait(session: AsyncSession) -> None:
        entering_lock.set()
        await acquire_graph_lock(session)

    monkeypatch.setattr(lifecycle_worker, "_acquire_graph_lock", observed_lock_wait)
    async with worker_session_factory() as blocker:
        await blocker.execute(select(func.pg_advisory_xact_lock(GRAPH_LOCK_ID)))
        linking = asyncio.create_task(link_opportunity(ctx, str(ids["child"])))
        await asyncio.wait_for(entering_lock.wait(), timeout=1)
        released_at = await blocker.scalar(select(func.clock_timestamp()))
        assert released_at is not None
        await blocker.commit()
        await linking

    async with worker_session_factory() as session:
        revisions = list(
            await session.scalars(
                select(LifecycleLink).where(LifecycleLink.child_opportunity_id == ids["child"])
            )
        )
        old = next(row for row in revisions if row.id == stale_id)
        current = next(row for row in revisions if row.status == "active")
        assert current.created_at >= released_at
        assert old.retracted_at == current.created_at
