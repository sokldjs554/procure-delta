from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, text

from app.api.company_profiles import get_current_owner_id
from app.db import get_session
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.service import persist_extraction
from app.main import app
from app.models import (
    CompanyProfile,
    EligibilityResult,
    Opportunity,
    OpportunityVersion,
    RankingResult,
    RawRecord,
    SourceRegistry,
)
from app.ranking.eligibility import (
    EligibilityOpportunity,
    EligibilityProfile,
    EvidenceClaim,
    _prepared_opportunity,
    _raw_claim,
    evaluate_eligibility,
    materialize_eligibility,
)
from app.ranking.ranker import materialize_ranking
from app.workers.eligibility import reconcile_eligibility_results
from tests.extraction.test_persistence import seeded as seeded


def claim(field: str, value: object) -> EvidenceClaim:
    return EvidenceClaim(
        field=field, value=value, evidence=({"kind": "raw", "json_pointer": f"/{field}"},)
    )


def profile(**changes: object) -> EligibilityProfile:
    values = {
        "regions": ("Seoul",),
        "certifications": ("ISO 27001",),
        "min_contract_amount": Decimal("100"),
        "max_contract_amount": Decimal("500"),
        "contract_currency": "KRW",
        "excluded_keywords": ("classified",),
    }
    values.update(changes)
    return EligibilityProfile(**values)


def opportunity(**changes: object) -> EligibilityOpportunity:
    values = {
        "regions": claim("regions", ["Seoul"]),
        "estimated_amount": claim("estimated_amount", "250"),
        "currency": claim("currency", "KRW"),
        "required_certifications": claim("required_certifications", ["ISO 27001"]),
        "text_fields": (claim("title", "Public cloud migration"),),
    }
    values.update(changes)
    return EligibilityOpportunity(**values)


@pytest.mark.parametrize(
    ("changed", "code"),
    [
        ({"regions": claim("regions", ["Busan"])}, "region_not_served"),
        ({"estimated_amount": claim("estimated_amount", "99")}, "amount_below_minimum"),
        ({"estimated_amount": claim("estimated_amount", "501")}, "amount_above_maximum"),
        (
            {"required_certifications": claim("required_certifications", ["ISMS-P"])},
            "missing_certification",
        ),
        (
            {"text_fields": (claim("participation_constraints", ["Classified supplier only"]),)},
            "explicit_exclusion",
        ),
    ],
)
def test_known_hard_failures_have_exact_codes_and_provenance(changed, code) -> None:
    result = evaluate_eligibility(profile(), opportunity(**changed))

    assert result.eligible is False
    reason = next(item for item in result.hard_failures if item.code == code)
    assert reason.evidence and reason.field
    assert result.warnings == ()


def test_unknown_and_cross_currency_inputs_need_review_without_inventing_failure() -> None:
    result = evaluate_eligibility(
        profile(),
        opportunity(
            regions=None,
            estimated_amount=claim("estimated_amount", "1000000"),
            currency=claim("currency", "USD"),
            required_certifications=None,
        ),
    )

    assert result.eligible is True
    assert result.hard_failures == ()
    assert {warning.code for warning in result.warnings} == {
        "region_unknown",
        "amount_currency_mismatch",
        "certifications_unknown",
    }
    assert result.needs_review is True
    assert result.allows_recommendation is False


def test_hard_failure_is_a_non_overridable_ranking_gate() -> None:
    result = evaluate_eligibility(profile(), opportunity(regions=claim("regions", ["Busan"])))

    assert result.allows_recommendation is False


def test_excluded_keyword_does_not_match_inside_another_word() -> None:
    result = evaluate_eligibility(
        profile(), opportunity(text_fields=(claim("title", "Unclassified cloud migration"),))
    )

    assert not any(reason.code == "explicit_exclusion" for reason in result.hard_failures)


@pytest.mark.asyncio
async def test_materialization_reuses_exact_inputs_and_profile_edit_creates_revision(
    session,
) -> None:
    source = SourceRegistry(
        code="eligibility-" + uuid4().hex,
        display_name="Synthetic",
        base_url="https://example.invalid",
    )
    raw = RawRecord(
        source_id=source.id,
        source_record_id="one",
        payload_json={
            "regions": ["Seoul"],
            "estimated_amount": "250",
            "currency": "KRW",
            "required_certifications": ["ISO 27001"],
        },
        payload_sha256="a" * 64,
        normalization_status="normalized",
    )
    item = Opportunity(
        canonical_key="eligibility-" + uuid4().hex, title="Cloud", buyer_name="Buyer"
    )
    company = CompanyProfile(
        owner_user_id="materialize-owner",
        display_name="Synthetic Test Co",
        synthetic_demo=True,
        regions=["Seoul"],
        certifications=["ISO 27001"],
        min_contract_amount=Decimal("100"),
        max_contract_amount=Decimal("500"),
        contract_currency="KRW",
    )
    session.add_all([source, item, company])
    await session.flush()
    raw.source_id = source.id
    session.add(raw)
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=item.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id="one",
        normalized_json=raw.payload_json,
        normalized_sha256="b" * 64,
    )
    session.add(version)
    await session.flush()

    first = await materialize_eligibility(session, company.id, version.id)
    replay = await materialize_eligibility(session, company.id, version.id)
    company.regions = ["Busan"]
    changed = await materialize_eligibility(session, company.id, version.id)

    assert replay.id == first.id
    assert changed.id != first.id and changed.eligible is False
    assert changed.profile_input_fingerprint != first.profile_input_fingerprint
    assert await session.scalar(select(func.count()).select_from(EligibilityResult)) == 2


@pytest.mark.asyncio
async def test_company_profile_api_is_typed_owner_scoped_and_validates_partial_updates(
    session,
) -> None:
    async def session_override():
        yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_owner_id] = lambda: "api-owner"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/company-profile",
                json={
                    "display_name": "Synthetic Demo Company",
                    "synthetic_demo": True,
                    "regions": ["Seoul"],
                    "certifications": ["ISO 27001"],
                    "min_contract_amount": "100",
                    "max_contract_amount": "500",
                    "contract_currency": "krw",
                },
            )
            assert created.status_code == 201
            assert created.json()["owner_user_id"] == "api-owner"
            assert created.json()["contract_currency"] == "KRW"
            invalid = await client.patch(
                "/api/v1/company-profile", json={"min_contract_amount": "600"}
            )
            assert invalid.status_code == 422
            fetched = await client.get("/api/v1/company-profile")
            assert (
                fetched.status_code == 200
                and fetched.json()["display_name"] == "Synthetic Demo Company"
            )
            duplicate = await client.post("/api/v1/company-profile", json={"display_name": "Other"})
            assert duplicate.status_code == 409
    finally:
        app.dependency_overrides.clear()
        await session.execute(
            delete(EligibilityResult).where(
                EligibilityResult.company_profile_id.in_(
                    select(CompanyProfile.id).where(CompanyProfile.owner_user_id == "api-owner")
                )
            )
        )
        await session.execute(
            delete(CompanyProfile).where(CompanyProfile.owner_user_id == "api-owner")
        )
        await session.commit()


@pytest.mark.asyncio
async def test_reconciliation_seeds_labeled_demo_and_materializes_current_versions(session) -> None:
    code = "eligibility-reconcile-" + uuid4().hex
    source = SourceRegistry(code=code, display_name="Synthetic", base_url="https://example.invalid")
    item = Opportunity(canonical_key=code, title="Cloud", buyer_name="Buyer")
    session.add_all([source, item])
    await session.flush()
    raw = RawRecord(
        source_id=source.id,
        source_record_id="one",
        payload_json={
            "regions": ["Seoul"],
            "estimated_amount": "25000000",
            "currency": "KRW",
            "required_certifications": ["ISO 27001"],
        },
        payload_sha256="c" * 64,
        normalization_status="normalized",
    )
    session.add(raw)
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=item.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id="one",
        normalized_json=raw.payload_json,
        normalized_sha256="d" * 64,
    )
    session.add(version)
    await session.flush()
    item.current_version_id = version.id

    outcome = await reconcile_eligibility_results({"session": session})
    demo = await session.scalar(
        select(CompanyProfile).where(CompanyProfile.owner_user_id == "synthetic-demo-owner")
    )

    assert outcome["materialized"] >= 1
    assert demo is not None and demo.synthetic_demo is True and "Synthetic" in demo.display_name
    assert (
        await session.scalar(
            select(func.count())
            .select_from(EligibilityResult)
            .where(
                EligibilityResult.company_profile_id == demo.id,
                EligibilityResult.opportunity_version_id == version.id,
            )
        )
        == 1
    )


def test_claim_requires_usable_normalized_value_and_labels_normalized_derivation() -> None:
    raw = RawRecord(
        source_id=uuid4(),
        source_record_id="claim",
        payload_json={"regions": ["Seoul"]},
        payload_sha256="e" * 64,
        normalization_status="normalized",
    )
    version = OpportunityVersion(
        opportunity_id=uuid4(),
        raw_record_id=uuid4(),
        version_number=1,
        source_record_id="claim",
        normalized_json={"currency": "KRW"},
        normalized_sha256="f" * 64,
    )

    assert _raw_claim(raw, version, "regions") is None
    derived = _raw_claim(raw, version, "currency")
    assert derived is not None and derived.value == "KRW"
    assert derived.evidence[0]["kind"] == "normalized"
    assert "json_pointer" not in derived.evidence[0]


@pytest.mark.asyncio
async def test_budget_never_pairs_raw_amount_with_attachment_only_currency(
    seeded, worker_session_factory
) -> None:
    async with worker_session_factory() as session:
        version = await session.get_one(OpportunityVersion, seeded)
        raw = await session.get_one(RawRecord, version.raw_record_id)
        raw.payload_json = {"estimated_amount": "125000000"}
        version.normalized_json = {
            "title": "Upstream title",
            "estimated_amount": "125000000",
        }
        await persist_extraction(session, version.id, DeterministicExtractor())
        prepared, _ = await _prepared_opportunity(session, version, DeterministicExtractor())

        assert prepared.estimated_amount is None
        assert prepared.currency is None


@pytest.mark.asyncio
async def test_current_extractor_enrichment_creates_new_eligibility_revision(
    seeded, worker_session_factory
) -> None:
    class LaterExtractor(DeterministicExtractor):
        extractor_version = "deterministic-fixture-v2"

    async with worker_session_factory() as session:
        company = CompanyProfile(
            owner_user_id="enrichment-owner-" + uuid4().hex,
            display_name="Synthetic Enrichment Company",
            synthetic_demo=True,
            regions=["Seoul"],
            certifications=["ISO 27001"],
            contract_currency="KRW",
        )
        session.add(company)
        await session.flush()
        first_extractor = DeterministicExtractor()
        await persist_extraction(session, seeded, first_extractor)
        first = await materialize_eligibility(
            session, company.id, seeded, extractor=first_extractor
        )
        later_extractor = LaterExtractor()
        await persist_extraction(session, seeded, later_extractor)
        enriched = await materialize_eligibility(
            session, company.id, seeded, extractor=later_extractor
        )

        assert enriched.id != first.id
        assert enriched.opportunity_input_fingerprint != first.opportunity_input_fingerprint


@pytest.mark.asyncio
async def test_extraction_backed_claims_drive_ranking_features_and_evidence(
    seeded, worker_session_factory
) -> None:
    async with worker_session_factory() as session:
        extractor = DeterministicExtractor()
        version = await session.get_one(OpportunityVersion, seeded)
        version.normalized_json = {}
        await session.flush()
        await persist_extraction(session, seeded, extractor)
        company = CompanyProfile(
            owner_user_id="ranking-extraction-owner-" + uuid4().hex,
            display_name="Synthetic Extraction Ranking Company",
            synthetic_demo=True,
            regions=["Seoul"],
            industries=["services"],
            capabilities=["cloud migration", "security monitoring", "incident response"],
            certifications=["ISO 27001", "GS certification"],
            min_contract_amount=Decimal("10000000"),
            max_contract_amount=Decimal("500000000"),
            contract_currency="KRW",
        )
        session.add(company)
        await session.flush()
        eligibility_row = await materialize_eligibility(
            session, company.id, seeded, extractor=extractor
        )
        before_deadline = await materialize_ranking(
            session,
            eligibility_row.id,
            as_of=version.effective_at.replace(
                year=2026, month=9, day=30, hour=8, minute=0, second=0, microsecond=0
            ),
            require_current=False,
            evaluation_epoch="daily:2026-09-30",
        )
        after_deadline = await materialize_ranking(
            session,
            eligibility_row.id,
            as_of=version.effective_at.replace(
                year=2026, month=9, day=30, hour=10, minute=0, second=0, microsecond=0
            ),
            require_current=False,
            evaluation_epoch="daily:2026-09-30:open",
        )

        assert before_deadline.id != after_deadline.id
        assert before_deadline.recommended is True
        assert after_deadline.recommended is False
        assert before_deadline.evaluation_epoch == "daily:2026-09-30:open"
        assert after_deadline.evaluation_epoch == "daily:2026-09-30:expired"
        assert before_deadline.feature_breakdown_json["amount"] != "0.00000"
        assert before_deadline.feature_breakdown_json["capability"] == "1.00000"
        assert (
            before_deadline.explanation_json["evidence"]["title"][0]["kind"]
            == "attachment_claim"
        )


@pytest.mark.asyncio
async def test_ranking_and_reconciliation_use_company_then_eligibility_lock_order(
    seeded, worker_session_factory
) -> None:
    async with worker_session_factory() as setup:
        company = CompanyProfile(
            owner_user_id="ranking-lock-owner-" + uuid4().hex,
            display_name="Synthetic Ranking Lock Company",
            synthetic_demo=True,
            regions=["Seoul"],
            industries=["services"],
            capabilities=["cloud migration"],
            certifications=["ISO 27001", "GS certification"],
            contract_currency="KRW",
        )
        setup.add(company)
        await setup.flush()
        eligibility_row = await materialize_eligibility(setup, company.id, seeded)
        company_id, eligibility_id = company.id, eligibility_row.id
        version = await setup.get_one(OpportunityVersion, seeded)
        as_of = version.effective_at + timedelta(days=1)
        await setup.commit()

    try:
        async with worker_session_factory() as reconciler, worker_session_factory() as direct:
            await reconciler.scalar(
                select(CompanyProfile)
                .where(CompanyProfile.id == company_id)
                .with_for_update()
            )
            direct_pid = await direct.scalar(text("SELECT pg_backend_pid()"))
            direct_task = asyncio.create_task(
                materialize_ranking(direct, eligibility_id, as_of=as_of)
            )
            for _ in range(100):
                waiting = await reconciler.scalar(
                    text(
                        "SELECT wait_event_type = 'Lock' FROM pg_stat_activity "
                        "WHERE pid = :pid"
                    ),
                    {"pid": direct_pid},
                )
                if waiting:
                    break
                await asyncio.sleep(0.01)
            assert waiting is True
            locked = await asyncio.wait_for(
                reconciler.scalar(
                    select(EligibilityResult)
                    .where(EligibilityResult.id == eligibility_id)
                    .with_for_update()
                ),
                timeout=1,
            )
            assert locked is not None
            await reconciler.commit()
            await asyncio.wait_for(direct_task, timeout=2)
            await direct.rollback()
    finally:
        async with worker_session_factory() as cleanup:
            await cleanup.execute(
                delete(RankingResult).where(RankingResult.company_profile_id == company_id)
            )
            await cleanup.execute(
                delete(EligibilityResult).where(
                    EligibilityResult.company_profile_id == company_id
                )
            )
            await cleanup.execute(delete(CompanyProfile).where(CompanyProfile.id == company_id))
            await cleanup.commit()
