from __future__ import annotations

import math
from collections.abc import Mapping, Sequence, Set
from typing import Any


def rate(numerator: int | float, denominator: int | float) -> float | None:
    """Undefined support stays null instead of becoming a misleading perfect score."""
    return numerator / denominator if denominator else None


def set_metrics(predicted: Set[str], expected: Set[str]) -> dict[str, int | float | None]:
    tp, fp, fn = len(predicted & expected), len(predicted - expected), len(expected - predicted)
    return {
        'tp': tp, 'fp': fp, 'fn': fn,
        'predicted_support': len(predicted), 'expected_support': len(expected),
        'precision': rate(tp, tp + fp), 'recall': rate(tp, tp + fn),
        'f1': rate(2 * tp, 2 * tp + fp + fn),
    }


def field_metrics(predicted: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    matches = {key: key in predicted and predicted[key] == value for key, value in expected.items()}
    return {
        'correct': sum(matches.values()), 'expected_fields': len(expected),
        'accuracy': rate(sum(matches.values()), len(expected)), 'per_field': matches,
        'missing': sorted(set(expected) - set(predicted)),
        'unexpected': sorted(set(predicted) - set(expected)),
        'exact_match': dict(predicted) == dict(expected),
    }


def ranking_metrics(
    ranked_ids: Sequence[str], relevance: Mapping[str, int], *, k: int,
) -> dict[str, int | float | None]:
    if k < 1 or len(set(ranked_ids)) != len(ranked_ids):
        raise ValueError('k must be positive and ranked ids must be unique')
    if any(grade < 0 or grade > 4 for grade in relevance.values()):
        raise ValueError('relevance grades must be in [0, 4]')
    selected = ranked_ids[:k]
    relevant = {key for key, grade in relevance.items() if grade > 0}
    hits = len(set(selected) & relevant)
    dcg = sum((2 ** relevance.get(key, 0) - 1) / math.log2(i + 2)
              for i, key in enumerate(selected))
    ideal = sum((2 ** grade - 1) / math.log2(i + 2)
                for i, grade in enumerate(sorted(relevance.values(), reverse=True)[:k]))
    return {
        'k': k, 'returned': len(selected), 'hits': hits, 'relevant_support': len(relevant),
        'recall_at_k': rate(hits, len(relevant)), 'ndcg_at_k': rate(dcg, ideal),
    }


def percentile(values: Sequence[float], percent: float) -> float | None:
    if not 0 <= percent <= 100 or any(not math.isfinite(x) for x in values):
        raise ValueError('percentiles require finite samples and a percentile in [0, 100]')
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)
