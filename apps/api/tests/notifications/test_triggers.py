from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (
    CompanyProfile,
    LifecycleLink,
    NotificationEvent,
    Opportunity,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
    Watchlist,
)

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


async def scenario(session):
    source = SourceRegistry(
        code="notifications-" + uuid4().hex,
        display_name="Synthetic",
        base_url="https://example.invalid",
    )
    company = CompanyProfile(
        owner_user_id=uuid4().hex,
        display_name="Synthetic",
        synthetic_demo=True,
        regions=["Seoul"],
        industries=["information technology"],
        capabilities=["cloud migration"],
        certifications=["ISO", "ALT"],
        min_contract_amount=Decimal("100"),
        max_contract_amount=Decimal("500"),
        contract_currency="KRW",
    )
    session.add_all([source, company])
    await session.flush()
    normalized = {
        "title": "Cloud migration",
        "description": "information technology cloud migration",
        "procurement_type": "information technology",
        "required_capabilities": ["cloud migration"],
        "estimated_amount": "300",
        "currency": "KRW",
        "regions": ["Seoul"],
        "required_certifications": ["ISO"],
        "participation_constraints": [],
        "published_at": "2026-09-15T00:00:00+00:00",
        "closes_at": "2026-09-30T00:00:00+00:00",
    }
    item, version = await add_item(session, source, normalized)
    return company, source, item, version


async def add_item(session, source, normalized, *, stage="tender", observed=NOW):
    item = Opportunity(
        canonical_key=uuid4().hex, title="Synthetic", buyer_name="Synthetic", lifecycle_stage=stage
    )
    session.add(item)
    await session.flush()
    version = await add_version(session, source, item, normalized, observed=observed)
    return item, version


async def add_version(session, source, item, normalized, *, before=None, observed=NOW):
    raw = RawRecord(
        source_id=source.id,
        source_record_id=uuid4().hex,
        payload_json=normalized,
        payload_sha256=uuid4().hex * 2,
        fetched_at=observed,
        normalization_status="normalized",
    )
    session.add(raw)
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=item.id,
        raw_record_id=raw.id,
        source_record_id=raw.source_record_id,
        version_number=before.version_number + 1 if before else 1,
        normalized_json=normalized,
        normalized_sha256=uuid4().hex * 2,
        effective_at=NOW - timedelta(days=1),
        previous_current_version_id=before.id if before else None,
        transition_kind="current" if before else "initial",
        transition_at=observed,
        documents_discovered_at=NOW,
        documents_completed_at=NOW,
    )
    session.add(version)
    await session.flush()
    item.current_version_id = version.id
    await session.flush()
    return version


async def events(session, company):
    return list(
        await session.scalars(
            select(NotificationEvent).where(NotificationEvent.user_id == company.owner_user_id)
        )
    )


@pytest.mark.asyncio
async def test_initial_recommendation_is_current_gated_once_per_owner_opportunity(session):
    from app.workers.notifications import reconcile_notifications

    company, _, item, version = await scenario(session)
    ctx = {"session": session, "notification_now": NOW}
    await reconcile_notifications(ctx)
    rows = await events(session, company)
    from app.models import RankingResult

    details = [row.explanation_json for row in await session.scalars(select(RankingResult))]
    assert [row.template_key for row in rows] == ["new_high_relevance"], details
    original = rows[0].id
    ctx["notification_now"] = NOW + timedelta(days=1)
    await reconcile_notifications(ctx)
    assert [row.id for row in await events(session, company)] == [original]
    # Retained recommended rows must not trigger another owner's currently blocked profile.
    company.certifications = []
    version.normalized_json = {**version.normalized_json, "required_certifications": ["ISO"]}
    raw = await session.get_one(RawRecord, version.raw_record_id)
    raw.payload_json = dict(version.normalized_json)
    other = CompanyProfile(
        owner_user_id=uuid4().hex,
        display_name="Synthetic blocked",
        synthetic_demo=True,
        regions=["Seoul"],
        capabilities=["cloud migration"],
        industries=["information technology"],
    )
    session.add(other)
    await session.flush()
    await reconcile_notifications(ctx)
    assert await events(session, other) == []


@pytest.mark.asyncio
async def test_replay_context_does_not_enqueue_live_notifications(session):
    from app.workers.notifications import reconcile_notifications

    company, _, _, _ = await scenario(session)
    await reconcile_notifications(
        {"session": session, "ranking_as_of": NOW, "notification_now": NOW}
    )
    assert await events(session, company) == []


@pytest.mark.asyncio
async def test_watch_triggers_use_transition_time_preferences_and_semantic_dedupe(session):
    from app.notifications.preferences import PreferenceValues, set_preferences
    from app.workers.notifications import reconcile_notifications

    company, source, item, before = await scenario(session)
    session.add(
        Watchlist(
            user_id=company.owner_user_id,
            opportunity_id=item.id,
            created_at=NOW - timedelta(hours=1),
        )
    )
    await set_preferences(
        session,
        company.owner_user_id,
        PreferenceValues(
            triggers=["watched_material_change", "deadline_changed", "eligibility_changed"]
        ),
    )
    after = await add_version(
        session,
        source,
        item,
        {
            **before.normalized_json,
            "closes_at": "2026-09-20T00:00:00+00:00",
            "required_certifications": ["ISO", "ALT"],
        },
        before=before,
    )
    ctx = {"session": session, "notification_now": NOW}
    await reconcile_notifications(ctx)
    rows = await events(session, company)
    assert {row.template_key for row in rows} == {
        "watched_material_change",
        "deadline_changed",
        "eligibility_changed",
    }
    original_ids = {row.id for row in rows}
    # Evidence-only revision: changing a gap creates an immutable delta revision, not a new alert.
    after.document_gaps_json = {"synthetic_gap": True}
    await session.flush()
    await reconcile_notifications(ctx)
    assert {row.id for row in await events(session, company)} == original_ids
    # A newly created watch cannot receive delayed evidence repair for a pre-watch transition.
    newer_owner = "newer-" + uuid4().hex
    session.add(
        Watchlist(
            user_id=newer_owner, opportunity_id=item.id, created_at=NOW + timedelta(minutes=1)
        )
    )
    ctx["notification_now"] = NOW + timedelta(minutes=2)
    await reconcile_notifications(ctx)
    assert not list(
        await session.scalars(
            select(NotificationEvent).where(NotificationEvent.user_id == newer_owner)
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "level"),
    [
        ("attachment_replaced", "medium"),
        ("attachment_removed", "medium"),
        ("contract_period", "medium"),
        ("attachment_added", "low"),
        ("no_op", None),
    ],
)
async def test_watched_changes_alert_at_actual_severity_but_no_op_does_not(session, change, level):
    from app.models import Attachment
    from app.notifications.preferences import PreferenceValues, set_preferences
    from app.workers.notifications import reconcile_notifications

    company, source, item, before = await scenario(session)
    before.normalized_json = {**before.normalized_json, "contract_period": "12 months"}
    raw = await session.get_one(RawRecord, before.raw_record_id)
    raw.payload_json = dict(before.normalized_json)
    session.add(
        Watchlist(
            user_id=company.owner_user_id,
            opportunity_id=item.id,
            created_at=NOW - timedelta(hours=1),
        )
    )
    await set_preferences(
        session, company.owner_user_id, PreferenceValues(triggers=["watched_material_change"])
    )
    after = await add_version(
        session,
        source,
        item,
        {**before.normalized_json, "contract_period": "18 months"}
        if change == "contract_period"
        else dict(before.normalized_json),
        before=before,
    )
    if change != "contract_period":
        for version, checksum in (
            (before, None if change == "attachment_added" else "a" * 64),
            (
                after,
                None
                if change == "attachment_removed"
                else ("b" * 64 if change == "attachment_replaced" else "a" * 64),
            ),
        ):
            if checksum is not None:
                session.add(
                    Attachment(
                        opportunity_version_id=version.id,
                        source_url="https://example.invalid/synthetic-terms.pdf",
                        filename="synthetic-terms.pdf",
                        sha256=checksum,
                        download_status="unsupported",
                    )
                )
    await session.flush()
    ctx = {"session": session, "notification_now": NOW}
    await reconcile_notifications(ctx)
    rows = await events(session, company)
    if level is None:
        assert rows == []
    else:
        assert len(rows) == 1
        assert rows[0].template_key == "watched_material_change"
        assert rows[0].payload_json["impact_level"] == level
        assert rows[0].payload_json["reason_codes"] == [
            "contract_period_changed" if change == "contract_period" else change
        ]
    original = [(row.id, dict(row.payload_json)) for row in rows]
    # An evidence-only revision retains the first alert; even a revised no-op stays silent.
    after.document_gaps_json = {"synthetic_evidence_revision": True}
    await session.flush()
    await reconcile_notifications(ctx)
    assert [(row.id, row.payload_json) for row in await events(session, company)] == original


@pytest.mark.asyncio
async def test_pending_current_delta_repair_suppresses_old_finalized_alerts(session):
    from app.delta.service import persist_delta
    from app.extraction.deterministic import DeterministicExtractor
    from app.workers.notifications import reconcile_notifications

    company, source, item, before = await scenario(session)
    company.capabilities = []
    company.industries = []
    session.add(
        Watchlist(
            user_id=company.owner_user_id,
            opportunity_id=item.id,
            created_at=NOW - timedelta(hours=1),
        )
    )
    after = await add_version(
        session,
        source,
        item,
        {**before.normalized_json, "closes_at": "2026-09-20T00:00:00+00:00"},
        before=before,
    )
    await persist_delta(session, after.id, DeterministicExtractor())
    after.documents_completed_at = None
    await session.flush()
    await reconcile_notifications({"session": session, "notification_now": NOW})
    assert await events(session, company) == []


@pytest.mark.asyncio
async def test_outcome_follows_active_ancestor_links_without_old_outcome_replay(session):
    from app.notifications.preferences import PreferenceValues, set_preferences
    from app.workers.notifications import reconcile_notifications

    company, source, item, before = await scenario(session)
    session.add(
        Watchlist(
            user_id=company.owner_user_id,
            opportunity_id=item.id,
            created_at=NOW - timedelta(hours=1),
        )
    )
    await set_preferences(
        session, company.owner_user_id, PreferenceValues(triggers=["outcome_published"])
    )
    award, awarded = await add_item(
        session, source, {**before.normalized_json, "lifecycle_stage": "award"}, stage="award"
    )
    link = LifecycleLink(
        parent_opportunity_id=item.id,
        child_opportunity_id=award.id,
        parent_version_id=before.id,
        child_version_id=awarded.id,
        relation_type="award",
        confidence=Decimal("1"),
        link_method="official_reference",
        status="active",
    )
    session.add(link)
    await session.flush()
    ctx = {"session": session, "notification_now": NOW}
    await reconcile_notifications(ctx)
    rows = await events(session, company)
    assert len(rows) == 1 and rows[0].template_key == "outcome_published"
    assert rows[0].payload_json["link_ids"] == [str(link.id)]
    assert rows[0].payload_json["outcome_version_id"] == str(awarded.id)
    await reconcile_notifications(ctx)
    assert len(await events(session, company)) == 1
    late_owner = "late-" + uuid4().hex
    session.add(
        Watchlist(user_id=late_owner, opportunity_id=item.id, created_at=NOW + timedelta(minutes=1))
    )
    ctx["notification_now"] = NOW + timedelta(minutes=2)
    await reconcile_notifications(ctx)
    assert not list(
        await session.scalars(
            select(NotificationEvent).where(NotificationEvent.user_id == late_owner)
        )
    )


@pytest.mark.asyncio
async def test_preferences_owner_boundary_and_disabled_delivery(session):
    from app.notifications.preferences import PreferenceValues, get_preferences, set_preferences
    from app.workers.notifications import deliver_notification, reconcile_notifications

    company, _, _, _ = await scenario(session)
    await set_preferences(
        session,
        company.owner_user_id,
        PreferenceValues(channels=["local"], triggers=["new_high_relevance"]),
    )
    assert (await get_preferences(session, "different-owner")).channels == ["local"]
    await reconcile_notifications({"session": session, "notification_now": NOW})
    rows = await events(session, company)
    assert len(rows) == 1
    await set_preferences(session, company.owner_user_id, PreferenceValues(enabled=False))
    await session.commit()
    assert (await deliver_notification({"session": session}, str(rows[0].id)))[
        "status"
    ] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["capabilities", "deadline", "certification", "unknown"])
async def test_retained_recommended_rank_cannot_notify_after_current_input_changes(
    session, changed
):
    from app.ranking.eligibility import materialize_eligibility
    from app.ranking.ranker import materialize_ranking
    from app.workers.notifications import reconcile_notifications

    company, _, _, version = await scenario(session)
    eligibility = await materialize_eligibility(session, company.id, version.id)
    prior = await materialize_ranking(
        session, eligibility.id, as_of=NOW, evaluation_epoch="daily:2026-09-16"
    )
    assert prior.recommended
    if changed == "capabilities":
        company.capabilities = []
        company.industries = []
    else:
        update = (
            {"closes_at": "2026-09-16T11:00:00+00:00"}
            if changed == "deadline"
            else {"required_certifications": ["UNHELD"] if changed == "certification" else []}
        )
        version.normalized_json = {**version.normalized_json, **update}
        raw = await session.get_one(RawRecord, version.raw_record_id)
        raw.payload_json = dict(version.normalized_json)
    await session.flush()
    await reconcile_notifications({"session": session, "notification_now": NOW})
    assert await events(session, company) == []


@pytest.mark.asyncio
async def test_delta_alert_delivery_is_cancelled_after_unwatch(session):
    from sqlalchemy import delete

    from app.notifications.preferences import PreferenceValues, set_preferences
    from app.workers.notifications import deliver_notification, reconcile_notifications

    company, source, item, before = await scenario(session)
    session.add(
        Watchlist(
            user_id=company.owner_user_id,
            opportunity_id=item.id,
            created_at=NOW - timedelta(hours=1),
        )
    )
    await set_preferences(
        session, company.owner_user_id, PreferenceValues(triggers=["deadline_changed"])
    )
    await add_version(
        session,
        source,
        item,
        {**before.normalized_json, "closes_at": "2026-09-20T00:00:00+00:00"},
        before=before,
    )
    await reconcile_notifications({"session": session, "notification_now": NOW})
    rows = await events(session, company)
    assert len(rows) == 1
    await session.execute(delete(Watchlist).where(Watchlist.user_id == company.owner_user_id))
    await session.commit()
    assert (await deliver_notification({"session": session}, str(rows[0].id)))[
        "status"
    ] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", ["profile", "pointer"])
async def test_reconcile_refreshes_cached_rows_before_current_materialization(session, stale):
    from sqlalchemy.orm.attributes import set_committed_value

    from app.workers.notifications import reconcile_notifications

    company, source, item, before = await scenario(session)
    if stale == "pointer":
        await add_version(
            session,
            source,
            item,
            {**before.normalized_json, "closes_at": "2026-09-16T11:00:00+00:00"},
            before=before,
        )
        set_committed_value(item, "current_version_id", before.id)
    else:
        company.capabilities, company.industries = [], []
        await session.flush()
        set_committed_value(company, "capabilities", ["cloud migration"])
        set_committed_value(company, "industries", ["information technology"])
    await reconcile_notifications({"session": session, "notification_now": NOW})
    assert await events(session, company) == []
