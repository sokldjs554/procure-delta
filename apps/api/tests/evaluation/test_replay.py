from __future__ import annotations

import importlib
from copy import deepcopy

import pytest


def replay():
    assert importlib.util.find_spec('app.evaluation.replay'), 'historical replay is missing'
    return importlib.import_module('app.evaluation.replay')


def event(**overrides):
    return dict(record_id='op-1', version_id='v1', effective_at='2026-09-01T00:00:00Z',
                observed_at='2026-09-02T00:00:00Z', created_at='2026-09-02T01:00:00Z',
                fields={'title': 'cloud migration', 'regions': ['Seoul'], 'currency': 'KRW',
                        'required_certifications': ['ISO 27001'], 'procurement_type': 'services',
                        'required_capabilities': ['cloud migration'], 'estimated_amount': '100',
                        'published_at': '2026-09-01T00:00:00Z',
                            'closes_at': '2026-10-01T00:00:00Z'},
                **overrides)


def test_replay_uses_effective_observed_and_materialized_times():
    r = replay()
    row = event()
    assert r.visible_versions([row], r.instant('2026-09-02T00:30:00Z')) == []
    assert r.visible_versions([row], r.instant('2026-09-03T00:00:00Z'))[0]['version_id'] == 'v1'
    late = deepcopy(row)
    late['observed_at'] = late['created_at'] = '2026-09-20T00:00:00Z'
    assert r.visible_versions([late], r.instant('2026-09-10T00:00:00Z')) == []


def test_late_old_record_cannot_replace_newer_effective_version():
    r = replay()
    early = event()
    old = deepcopy(early)
    old.update(version_id='old-late', effective_at='2026-08-01T00:00:00Z',
               observed_at='2026-09-05T00:00:00Z', created_at='2026-09-05T01:00:00Z')
    assert r.visible_versions([early, old],
        r.instant('2026-09-10T00:00:00Z'))[0]['version_id'] == 'v1'


def test_future_enrichment_is_removed_not_read_from_current_pointer():
    r = replay()
    row = event()
    row['enrichment'] = {'available_at': '2026-10-01T00:00:00Z',
                         'fields': {'required_capabilities': ['future-secret']},
                             'extraction_id': 'future'}
    visible = r.visible_versions([row], r.instant('2026-09-03T00:00:00Z'))[0]
    assert visible['fields']['required_capabilities'] == ['cloud migration']
    assert visible.get('extraction_id') is None
    assert row['enrichment']['fields']['required_capabilities'] == ['future-secret']


def test_future_profile_not_used_and_naive_dates_rejected():
    r = replay()
    with pytest.raises(ValueError):
        r.instant('2026-09-01')
    with pytest.raises(ValueError):
        r.profile_at([{'available_at': '2026-10-01T00:00:00Z', 'id': 'later', 'fields': {}}],
                     r.instant('2026-09-01T00:00:00Z'))


def test_duplicate_version_identifiers_are_rejected():
    r = replay()
    with pytest.raises(ValueError):
        r.visible_versions([event(), event()], r.instant('2026-09-04T00:00:00Z'))


def test_future_outcome_fields_never_enter_ranking_features():
    r = replay()
    row = event()
    row['fields']['award_winner'] = 'cloud migration'
    row['fields']['contract_outcome'] = 'future-secret'
    result = r.visible_versions([row], r.instant('2026-09-04T00:00:00Z'))[0]
    assert 'award_winner' not in result['fields']
    assert 'contract_outcome' not in result['fields']
