"""Bitemporal replay: upstream effectiveness AND availability must precede as_of.

No database current pointers, live company profiles, outcomes, or newly available
extractions are substituted into past decisions. Frozen labels are never features.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.ranking.eligibility import (
    EligibilityOpportunity,
    EligibilityProfile,
    EvidenceClaim,
    evaluate_eligibility,
)
from app.ranking.features import RankingOpportunity, RankingProfile
from app.ranking.ranker import RankingEligibility, rank_opportunity

FEATURE_FIELDS = frozenset({
    'title', 'buyer_name', 'procurement_type', 'regions', 'estimated_amount', 'currency',
    'published_at', 'closes_at', 'required_certifications', 'required_capabilities',
    'participation_constraints', 'description', 'lifecycle_stage',
})
PROFILE_FIELDS = frozenset({
    'regions', 'certifications', 'min_contract_amount', 'max_contract_amount',
    'contract_currency', 'excluded_keywords', 'industries', 'capabilities',
})


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('replay timestamps must include a timezone')
    return parsed.astimezone(UTC)


def visible_versions(events: Sequence[dict[str, Any]], as_of: datetime) -> list[dict[str, Any]]:
    if as_of.tzinfo is None:
        raise ValueError('as_of must include a timezone')
    selected: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for event in events:
        identifier = str(event['version_id'])
        if identifier in seen:
            raise ValueError('version_id must be globally unique in a replay dataset')
        seen.add(identifier)
        times = [instant(event[key]) for key in ('effective_at', 'observed_at', 'created_at')]
        if max(times) > as_of:
            continue
        # Select the newest effective input among versions actually available then.
        key = str(event['record_id'])
        rank = (times[0], times[1], times[2], identifier)
        previous = selected.get(key)
        if previous is not None and rank <= previous['_order']:
            continue
        fields = {k: deepcopy(v) for k, v in event['fields'].items() if k in FEATURE_FIELDS}
        enriched = event.get('enrichment')
        extraction_id = None
        if enriched and instant(enriched['available_at']) <= as_of:
            fields.update({k: deepcopy(v) for k, v in enriched['fields'].items()
                           if k in FEATURE_FIELDS})
            extraction_id = enriched['extraction_id']
        selected[key] = {
            'record_id': key, 'version_id': identifier, 'fields': fields,
            'effective_at': event['effective_at'], 'observed_at': event['observed_at'],
            'created_at': event['created_at'], 'extraction_id': extraction_id, '_order': rank,
        }
    return [{k: v for k, v in row.items() if k != '_order'}
            for _, row in sorted(selected.items())]


def profile_at(profiles: Sequence[dict[str, Any]], as_of: datetime) -> dict[str, Any]:
    available = [p for p in profiles if instant(p['available_at']) <= as_of]
    if not available:
        raise ValueError('no historical profile was available at as_of')
    chosen = max(available, key=lambda p: (instant(p['available_at']), str(p['id'])))
    if not {'industries', 'capabilities'}.issubset(chosen['fields']):
        raise ValueError(
            'historical profile lacks ranking fields; refusing current-profile fallback'
        )
    return deepcopy(chosen)


def _decimal(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def decision_for(fields: Mapping[str, Any], profile: Mapping[str, Any], *, as_of: datetime,
                 evidence_id: str) -> dict[str, Any]:
    def claim(field: str) -> EvidenceClaim | None:
        value = fields.get(field)
        if value is None:
            return None
        return EvidenceClaim(field, value, ({'kind': 'frozen_eval', 'snapshot_id': evidence_id,
                                             'field': field},))

    hard_profile = EligibilityProfile(
        regions=tuple(profile.get('regions', [])),
        certifications=tuple(profile.get('certifications', [])),
        min_contract_amount=_decimal(profile.get('min_contract_amount')),
        max_contract_amount=_decimal(profile.get('max_contract_amount')),
        contract_currency=profile.get('contract_currency'),
        excluded_keywords=tuple(profile.get('excluded_keywords', [])),
        industries=tuple(profile.get('industries', [])),
        capabilities=tuple(profile.get('capabilities', [])),
    )
    texts = tuple(c for f in ('title', 'description') if (c := claim(f)) is not None)
    hard = evaluate_eligibility(hard_profile, EligibilityOpportunity(
        regions=claim('regions'), estimated_amount=claim('estimated_amount'),
        currency=claim('currency'), required_certifications=claim('required_certifications'),
        text_fields=texts,
    ))
    ranked = rank_opportunity(
        RankingProfile(industries=hard_profile.industries, capabilities=hard_profile.capabilities,
                       min_contract_amount=hard_profile.min_contract_amount,
                       max_contract_amount=hard_profile.max_contract_amount,
                       contract_currency=hard_profile.contract_currency),
        RankingOpportunity(
            title=str(fields.get('title', '')), body=str(fields.get('description', '')),
            category=fields.get('procurement_type'),
            required_capabilities=tuple(fields.get('required_capabilities', [])),
            estimated_amount=_decimal(fields.get('estimated_amount')),
            currency=fields.get('currency'),
            published_at=instant(fields['published_at']) if fields.get('published_at') else None,
            deadline=instant(fields['closes_at']) if fields.get('closes_at') else None,
        ),
        RankingEligibility(hard.eligible, tuple(x.code for x in hard.hard_failures),
                           tuple(x.code for x in hard.warnings)), as_of=as_of,
    )
    return {
        'allows_recommendation': hard.allows_recommendation,
        'hard_failure_codes': [x.code for x in hard.hard_failures],
        'warning_codes': [x.code for x in hard.warnings],
        'score': float(ranked.final_score), 'recommended': ranked.recommended,
        'features': {k: str(v) for k, v in ranked.features.items()},
    }


def replay_at(events: Sequence[dict[str, Any]], profiles: Sequence[dict[str, Any]],
              as_of: datetime) -> dict[str, Any]:
    profile = profile_at(profiles, as_of)
    decisions = [
        {**row, **decision_for(row['fields'], profile['fields'], as_of=as_of,
                              evidence_id=row['version_id'])}
        for row in visible_versions(events, as_of)
    ]
    decisions.sort(key=lambda item: (-item['score'], item['record_id']))
    return {
        'as_of': as_of.isoformat(), 'profile_id': profile['id'],
        'profile_available_at': profile['available_at'], 'decisions': decisions,
        # Evaluate full hard-gated ordering, not only the thresholded recommendation set.
        'ranked_ids': [r['record_id'] for r in decisions if r['allows_recommendation']],
        'outcome_features_used': False,
    }
