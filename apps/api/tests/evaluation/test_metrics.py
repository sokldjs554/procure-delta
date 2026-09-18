from __future__ import annotations

import importlib
import math

import pytest


def metrics():
    assert importlib.util.find_spec('app.evaluation.metrics'), 'evaluation metrics are missing'
    return importlib.import_module('app.evaluation.metrics')


def test_prf_counts_false_positives_and_misses():
    value = metrics().set_metrics({'a', 'x'}, {'a', 'b', 'c'})
    assert value['tp'] == 1 and value['fp'] == 1 and value['fn'] == 2
    assert value['precision'] == 0.5
    assert value['recall'] == pytest.approx(1 / 3)


def test_empty_support_is_not_perfect_accuracy():
    value = metrics().set_metrics(set(), set())
    assert value['precision'] is None and value['recall'] is None
    assert metrics().rate(0, 0) is None


def test_ranking_handles_missing_and_nonrelevant_results():
    m = metrics()
    result = m.ranking_metrics(['x', 'a'], {'a': 3, 'b': 1}, k=2)
    assert result['recall_at_k'] == 0.5
    assert result['ndcg_at_k'] == pytest.approx((7 / math.log2(3)) / (7 + 1 / math.log2(3)))
    assert result['relevant_support'] == 2


def test_ranking_zero_support_is_undefined():
    result = metrics().ranking_metrics(['x'], {}, k=3)
    assert result['recall_at_k'] is None and result['ndcg_at_k'] is None


@pytest.mark.parametrize('ranked,k', [(['a', 'a'], 2), (['a'], 0)])
def test_ranking_rejects_invalid_input(ranked, k):
    with pytest.raises(ValueError):
        metrics().ranking_metrics(ranked, {'a': 1}, k=k)


def test_metrics_include_failed_fields_in_denominator():
    result = metrics().field_metrics({'title': 'a'}, {'title': 'a', 'currency': 'KRW'})
    assert result['accuracy'] == 0.5 and result['expected_fields'] == 2
    assert result['missing'] == ['currency']


def test_percentiles_use_all_requests_including_failures():
    m = metrics()
    assert m.percentile([1, 2, 3, 4, 5], 95) == pytest.approx(4.8)
    assert m.percentile([], 95) is None
    with pytest.raises(ValueError):
        m.percentile([float('nan')], 95)
