from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (
    CompanyProfile,
    EligibilityResult,
    Opportunity,
    OpportunityVersion,
    RankingResult,
    RawRecord,
    SourceRegistry,
)
from app.ranking.eligibility import materialize_eligibility
from app.ranking.features import RankingOpportunity, RankingProfile
from app.ranking.ranker import (
    RANKING_VERSION,
    SemanticReranker,
    materialize_ranking,
    rank_opportunity,
)
from app.workers.ranking import reconcile_ranking_results

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def profile() -> RankingProfile:
    return RankingProfile(
        industries=("information technology",),
        capabilities=("cloud migration", "document processing"),
        min_contract_amount=Decimal("100"),
        max_contract_amount=Decimal("500"),
        contract_currency="KRW",
    )


def opportunity(**changes: object) -> RankingOpportunity:
    values: dict[str, object] = {
        "title": "Cloud migration and document processing service",
        "body": "Information technology modernization",
        "category": "information technology",
        "required_capabilities": ("cloud migration", "document processing"),
        "estimated_amount": Decimal("300"),
        "currency": "KRW",
        "published_at": datetime(2026, 9, 14, tzinfo=UTC),
        "deadline": datetime(2026, 9, 30, tzinfo=UTC),
        "evidence": {"title": [{"kind": "raw", "json_pointer": "/title"}]},
    }
    values.update(changes)
    return RankingOpportunity(**values)  # type: ignore[arg-type]


def eligibility(*, eligible: bool = True, warnings: tuple[str, ...] = ()):
    from app.ranking.ranker import RankingEligibility

    return RankingEligibility(eligible=eligible, hard_failure_codes=(), warning_codes=warnings)


def test_baseline_features_are_normalized_and_explained() -> None:
    result = rank_opportunity(profile(), opportunity(), eligibility(), as_of=NOW)

    assert result.recommended is True
    assert set(result.features) == {
        "lexical",
        "capability",
        "category",
        "amount",
        "recency_deadline",
    }
    assert all(Decimal("0") <= score <= Decimal("1") for score in result.features.values())
    assert result.features["capability"] == Decimal("1")
    assert result.features["category"] == Decimal("1")
    assert result.features["amount"] == Decimal("1")
    assert result.explanation["as_of"] == NOW.isoformat()
    assert result.explanation["evidence"]["title"][0]["json_pointer"] == "/title"


def test_amount_unknown_or_cross_currency_is_neutral_and_visible() -> None:
    unknown = rank_opportunity(
        profile(), opportunity(estimated_amount=None, currency=None), eligibility(), as_of=NOW
    )
    mismatch = rank_opportunity(profile(), opportunity(currency="USD"), eligibility(), as_of=NOW)

    assert unknown.features["amount"] == Decimal("0")
    assert mismatch.features["amount"] == Decimal("0")
    assert unknown.explanation["feature_reasons"]["amount"] == "amount_unknown"
    assert mismatch.explanation["feature_reasons"]["amount"] == "currency_mismatch"


def test_frozen_as_of_controls_recency_and_rejects_future_knowledge() -> None:
    current = rank_opportunity(profile(), opportunity(), eligibility(), as_of=NOW)
    later = rank_opportunity(
        profile(), opportunity(), eligibility(), as_of=datetime(2026, 10, 2, tzinfo=UTC)
    )

    assert current.features["recency_deadline"] > later.features["recency_deadline"]
    with pytest.raises(ValueError, match="published after as_of"):
        rank_opportunity(
            profile(),
            opportunity(published_at=datetime(2026, 9, 17, tzinfo=UTC)),
            eligibility(),
            as_of=NOW,
        )
    expired = rank_opportunity(
        profile(),
        opportunity(deadline=datetime(2026, 9, 16, 11, tzinfo=UTC)),
        eligibility(),
        as_of=NOW,
    )
    assert expired.recommended is False
    assert expired.explanation["deadline_state"] == "expired"


class MaximumSemantic(SemanticReranker):
    def score(self, profile: RankingProfile, opportunity: RankingOpportunity) -> Decimal:
        del profile, opportunity
        return Decimal("1")


def test_semantic_reranker_is_disabled_by_default_and_cannot_rescue_gate() -> None:
    hard = rank_opportunity(
        profile(),
        opportunity(),
        eligibility(eligible=False),
        as_of=NOW,
        semantic_reranker=MaximumSemantic(),
        semantic_enabled=True,
    )
    uncertain = rank_opportunity(
        profile(), opportunity(), eligibility(warnings=("amount_unknown",)), as_of=NOW
    )

    assert hard.semantic_score == Decimal("1") and hard.recommended is False
    assert uncertain.recommended is False
    assert uncertain.explanation["eligibility_warnings"] == ["amount_unknown"]


def test_score_between_point_four_and_point_six_is_not_recommended() -> None:
    result = rank_opportunity(
        profile(),
        opportunity(
            title="Cloud",
            body="",
            category="information technology",
            required_capabilities=("cloud migration",),
            estimated_amount=None,
            currency=None,
            published_at=None,
            deadline=None,
        ),
        eligibility(),
        as_of=NOW,
    )

    assert Decimal("0.40") <= result.final_score < Decimal("0.60")
    assert result.recommended is False


@pytest.mark.asyncio
async def test_materialization_is_input_qualified_and_worker_ranks_demo_match(session) -> None:
    source = SourceRegistry(
        code="ranking-" + uuid4().hex,
        display_name="Synthetic",
        base_url="https://example.invalid",
    )
    company = CompanyProfile(
        owner_user_id="ranking-owner-" + uuid4().hex,
        display_name="Synthetic Ranking Company",
        synthetic_demo=True,
        regions=["Seoul"],
        industries=["information technology"],
        capabilities=["cloud migration", "document processing"],
        certifications=["ISO 27001"],
        min_contract_amount=Decimal("10000000"),
        max_contract_amount=Decimal("500000000"),
        contract_currency="KRW",
    )
    item = Opportunity(canonical_key="ranking-" + uuid4().hex, title="Cloud", buyer_name="Buyer")
    session.add_all([source, company, item])
    await session.flush()
    normalized = {
        "title": "Cloud migration document processing",
        "description": "Information technology modernization",
        "procurement_type": "information technology",
        "required_capabilities": ["cloud migration", "document processing"],
        "estimated_amount": "150000000",
        "currency": "KRW",
        "regions": ["Seoul"],
        "required_certifications": ["ISO 27001"],
        "published_at": "2026-09-14T00:00:00+00:00",
        "closes_at": "2026-09-30T00:00:00+00:00",
    }
    raw = RawRecord(
        source_id=source.id,
        source_record_id="ranking-one",
        payload_json=normalized,
        payload_sha256="9" * 64,
        normalization_status="normalized",
    )
    session.add(raw)
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=item.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id="ranking-one",
        normalized_json=normalized,
        normalized_sha256="8" * 64,
        effective_at=datetime(2026, 9, 14, tzinfo=UTC),
    )
    session.add(version)
    await session.flush()
    item.current_version_id = version.id
    eligibility_row = EligibilityResult(
        company_profile_id=company.id,
        opportunity_version_id=version.id,
        eligible=True,
        hard_fail_reasons_json={"items": []},
        warnings_json={"items": []},
        ruleset_version="hard-eligibility-v1",
        profile_input_fingerprint="1" * 64,
        opportunity_input_fingerprint="2" * 64,
        input_provenance_json={
            "profile": {
                "industries": list(company.industries),
                "capabilities": list(company.capabilities),
                "min_contract_amount": str(company.min_contract_amount),
                "max_contract_amount": str(company.max_contract_amount),
                "contract_currency": company.contract_currency,
            },
            "opportunity": {
                "version_id": str(version.id),
                "normalized_sha256": version.normalized_sha256,
                "claims": {},
                "ranking_claims": {
                    "title": {"value": normalized["title"], "evidence": []},
                    "description": {
                        "value": normalized["description"],
                        "evidence": [],
                    },
                    "body": None,
                    "category": {
                        "value": normalized["procurement_type"],
                        "evidence": [],
                    },
                    "required_capabilities": {
                        "value": normalized["required_capabilities"],
                        "evidence": [],
                    },
                    "estimated_amount": {
                        "value": normalized["estimated_amount"],
                        "evidence": [],
                    },
                    "currency": {"value": normalized["currency"], "evidence": []},
                    "published_at": {
                        "value": normalized["published_at"],
                        "evidence": [],
                    },
                    "deadline": {"value": normalized["closes_at"], "evidence": []},
                },
            }
        },
    )
    session.add(eligibility_row)
    await session.flush()

    first = await materialize_ranking(
        session,
        eligibility_row.id,
        as_of=NOW,
        require_current=False,
        evaluation_epoch="daily:2026-09-16:open",
    )
    replay = await materialize_ranking(
        session,
        eligibility_row.id,
        as_of=datetime(2026, 9, 16, 13, tzinfo=UTC),
        require_current=False,
        evaluation_epoch="daily:2026-09-16:open",
    )
    changed_eligibility = EligibilityResult(
        company_profile_id=company.id,
        opportunity_version_id=version.id,
        eligible=True,
        hard_fail_reasons_json={"items": []},
        warnings_json={"items": []},
        ruleset_version="hard-eligibility-v1",
        profile_input_fingerprint="3" * 64,
        opportunity_input_fingerprint="2" * 64,
        input_provenance_json=eligibility_row.input_provenance_json,
    )
    session.add(changed_eligibility)
    await session.flush()
    refreshed = await materialize_ranking(
        session,
        changed_eligibility.id,
        as_of=datetime(2026, 9, 16, 13, tzinfo=UTC),
        require_current=False,
        evaluation_epoch="daily:2026-09-16:open",
    )
    outcome = await reconcile_ranking_results({"session": session, "ranking_now": NOW})

    assert replay.id == first.id
    assert refreshed.id != first.id
    assert first.ranking_version == RANKING_VERSION
    assert first.recommended is True and first.final_score >= Decimal("0.70")
    assert first.eligibility_result_id == eligibility_row.id
    assert first.input_provenance_json["eligibility_result_id"] == str(eligibility_row.id)
    assert first.as_of == NOW and first.evaluation_epoch == "daily:2026-09-16:open"
    assert set(first.feature_breakdown_json) == {
        "lexical",
        "capability",
        "category",
        "amount",
        "recency_deadline",
    }
    assert outcome["recommended"] >= 1
    demo = await session.scalar(
        select(CompanyProfile).where(CompanyProfile.owner_user_id == "synthetic-demo-owner")
    )
    assert demo is not None
    demo_ranking = await session.scalar(
        select(RankingResult).where(
            RankingResult.company_profile_id == demo.id,
            RankingResult.opportunity_version_id == version.id,
        )
    )
    assert demo_ranking is not None and demo_ranking.recommended is True
    stored = await session.scalar(select(type(first)).where(type(first).id == first.id))
    assert stored is not None
    current = await materialize_eligibility(session, company.id, version.id)
    before = await materialize_ranking(session, current.id, as_of=NOW)
    company.industries = ["construction"]
    company.capabilities = ["bridge building"]
    changed_eligibility = await materialize_eligibility(
        session, company.id, version.id
    )
    after = await materialize_ranking(session, changed_eligibility.id, as_of=NOW)
    replay = await materialize_ranking(
        session, current.id, as_of=NOW, require_current=False
    )

    assert changed_eligibility.id != current.id
    assert after.id != before.id and after.final_score < before.final_score
    assert replay.id == before.id and replay.final_score == before.final_score
