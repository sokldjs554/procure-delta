from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.delta.engine import DeltaSnapshot, compute_delta
from app.extraction.base import StructuredExtractor
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.schemas import DocumentBundle, DocumentPage, StructuredFields
from app.extraction.validation import validate_extraction
from app.lifecycle.linker import LinkCandidate, link_candidate
from app.models import OpportunityVersion, RawRecord

from .metrics import field_metrics, percentile, ranking_metrics, rate, set_metrics
from .provenance import load_dataset, provenance
from .replay import instant, replay_at

SAFE_PROVIDER_ERROR_TYPES = frozenset({
    'invalid_request_error', 'authentication_error', 'permission_error', 'not_found_error',
    'request_too_large', 'rate_limit_error', 'api_error', 'overloaded_error', 'billing_error',
    'insufficient_quota',
})


def _http_diagnostics(error: Exception) -> dict[str, Any]:
    """Keep bounded status/allowlisted labels, never provider text, URLs or headers."""
    result: dict[str, Any] = {
        'http_status': None, 'provider_error_type': None, 'provider_hint': None,
    }
    if not isinstance(error, httpx.HTTPStatusError):
        return result
    result['http_status'] = error.response.status_code
    try:
        envelope = error.response.json()
    except ValueError:
        return result
    detail = envelope.get('error') if isinstance(envelope, dict) else None
    if not isinstance(detail, dict):
        return result
    error_type = detail.get('type')
    if isinstance(error_type, str) and error_type in SAFE_PROVIDER_ERROR_TYPES:
        result['provider_error_type'] = error_type
    # These are diagnostic hints, not a copy of an upstream message or a proven cause.
    message = detail.get('message')
    if isinstance(message, str) and len(message) <= 8192:
        if 'credit balance is too low' in message.lower():
            result['provider_hint'] = 'check_api_billing'
        elif 'anthropic-workspace-id' in message.lower():
            result['provider_hint'] = 'check_workspace_selection'
    return result


def bundle(text: str, kind: str = 'native_text') -> DocumentBundle:
    return DocumentBundle(pages=(DocumentPage(
        attachment_sha256=hashlib.sha256(text.encode()).hexdigest(), page_number=1,
        text=text, parser_kind=kind, parser_version='frozen-eval-v1',
    ),))


def canonical(fields: Mapping[str, Any]) -> dict[str, Any]:
    values = {k: deepcopy(v) for k, v in fields.items()
              if k not in {'evidence', 'schema_version'} and v is not None}
    for key, value in values.items():
        if key == 'estimated_amount':
            values[key] = format(Decimal(str(value)).normalize(), 'f')
        elif key in {'published_at', 'closes_at'}:
            values[key] = instant(str(value)).isoformat()
        elif isinstance(value, list):
            values[key] = sorted(value)
    return values


async def extraction_eval(cases: list[dict[str, Any]], extractor: StructuredExtractor,
                          *, gated: bool = False) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    durations: list[float] = []
    calls = schema_failures = correct_fields = expected_fields = 0
    expected_rejects: set[str] = set()
    observed_rejects: set[str] = set()
    expected_conditions: set[str] = set()
    observed_conditions: set[str] = set()
    token_in: list[int | None] = []
    token_out: list[int | None] = []
    costs: list[Decimal | None] = []
    date_correct = date_support = amount_correct = amount_support = 0
    for case in cases:
        document = bundle(case['text'])
        start = time.perf_counter()
        used_hosted = extractor.provider != 'local'
        error_type = None
        http_diagnostics: dict[str, Any] = {
            'http_status': None, 'provider_error_type': None, 'provider_hint': None,
        }
        call_counted = False
        usage_recorded = False
        response_diagnostics = None
        schema_error_fields: list[str] = []
        grounding_issues: list[dict[str, Any]] = []
        rejection_stage = None
        row_prompt_tokens = row_completion_tokens = None
        try:
            if gated:
                proposal = await DeterministicExtractor().extract(document)
                if not validate_extraction(proposal, document).valid:
                    calls += int(used_hosted)
                    call_counted = True
                    proposal = await extractor.extract(document)
                else:
                    used_hosted = False
            else:
                calls += int(used_hosted)
                call_counted = True
                proposal = await extractor.extract(document)
            if used_hosted:
                row_prompt_tokens, row_completion_tokens = (
                    proposal.prompt_tokens, proposal.completion_tokens
                )
                if proposal.diagnostics is not None:
                    response_diagnostics = proposal.diagnostics.model_dump(mode='json')
                token_in.append(proposal.prompt_tokens)
                token_out.append(proposal.completion_tokens)
                costs.append(proposal.estimated_cost)
                usage_recorded = True
            try:
                StructuredFields.model_validate(proposal.output)
                schema_ok = True
            except ValidationError as error:
                schema_ok = False
                known_fields = StructuredFields.model_fields
                schema_error_fields = sorted({
                    str(item['loc'][0]) if item['loc'] and item['loc'][0] in known_fields
                    else 'unknown'
                    for item in error.errors(include_input=False, include_context=False,
                                             include_url=False)
                })
            report = validate_extraction(proposal, document)
            grounding_issues = [issue.model_dump(mode='json') for issue in report.grounding_issues]
            predicted = canonical(report.fields.model_dump(mode='json')) if report.fields else {}
            valid = report.valid
            if not valid:
                if response_diagnostics and response_diagnostics['status'] != 'parsed':
                    rejection_stage = 'response'
                else:
                    rejection_stage = 'schema' if not schema_ok else 'grounding'
        except Exception as error:
            # Never serialize provider errors, URLs or raw secret-bearing response bodies.
            if used_hosted and call_counted and not usage_recorded:
                token_in.append(None)
                token_out.append(None)
                costs.append(None)
            schema_ok, valid, predicted, error_type = False, False, {}, type(error).__name__
            http_diagnostics = _http_diagnostics(error)
            rejection_stage = 'execution'
        elapsed = (time.perf_counter() - start) * 1000
        durations.append(elapsed)
        schema_failures += int(not schema_ok)
        if not case['expected_valid']:
            expected_rejects.add(case['id'])
        if not valid:
            observed_rejects.add(case['id'])
        expected = canonical(case['expected_fields'])
        fields = field_metrics(predicted, expected)
        if case['expected_valid']:
            correct_fields += fields['correct']
            expected_fields += fields['expected_fields']
            for key in ('published_at', 'closes_at'):
                if key in expected:
                    date_support += 1
                    date_correct += int(predicted.get(key) == expected[key])
            if 'estimated_amount' in expected:
                amount_support += 1
                amount_correct += int(
                    predicted.get('estimated_amount') == expected['estimated_amount']
                )
            for key in ('required_certifications', 'required_capabilities',
                'participation_constraints'):
                expected_conditions.update(f"{case['id']}:{key}:{x}" for x in expected.get(key, []))
                observed_conditions.update(
                    f"{case['id']}:{key}:{x}" for x in predicted.get(key, [])
                )
        rows.append({'id': case['id'], 'expected_valid': case['expected_valid'], 'valid': valid,
                     'schema_valid': schema_ok, 'fields': fields, 'trusted_fields': predicted,
                     'rejection_stage': rejection_stage, 'schema_error_fields': schema_error_fields,
                     'grounding_issues': grounding_issues,
                     'response_diagnostics': response_diagnostics,
                     'prompt_tokens': row_prompt_tokens, 'completion_tokens': row_completion_tokens,
                     'duration_ms': elapsed, 'error_type': error_type, **http_diagnostics})
    n = len(cases)
    all_costs_known = bool(costs) and all(c is not None for c in costs)
    valid_gold = [r for r in rows if r['expected_valid']]
    execution_errors = sum(r['error_type'] is not None for r in rows)
    return {
        'status': 'failed' if execution_errors else 'measured',
        'reason': 'execution errors; quality and savings are not validated' if execution_errors
        else None,
        'execution_errors': execution_errors,
        'extractor': {'provider': extractor.provider, 'model': extractor.model,
                      'version': extractor.extractor_version,
                      **({'prompt_contract_sha256': extractor.prompt_contract_sha256}
                         if hasattr(extractor, 'prompt_contract_sha256') else {})},
        'documents': n, 'field_accuracy': rate(correct_fields,
            expected_fields),
        'correct_fields': correct_fields, 'expected_fields': expected_fields,
        'document_exact_accuracy': rate(sum(r['fields']['exact_match'] for r in valid_gold),
                                        len(valid_gold)),
        'exact_document_support': len(valid_gold),
        'date_accuracy': rate(date_correct, date_support), 'date_support': date_support,
        'amount_accuracy': rate(amount_correct, amount_support), 'amount_support': amount_support,
        'required_conditions': set_metrics(observed_conditions, expected_conditions),
        'rejection_detection': set_metrics(observed_rejects, expected_rejects),
        'schema_violation_rate': rate(schema_failures, n), 'schema_failures': schema_failures,
        'grounded_accepted_documents': sum(r['valid'] for r in rows),
        'grounded_acceptance_rate': rate(sum(r['valid'] for r in rows), n),
        'hosted_calls': calls,
        'prompt_tokens': sum(t for t in token_in if t is not None)
        if calls and all(t is not None for t in token_in) else None,
        'completion_tokens': sum(t for t in token_out if t is not None)
        if calls and all(t is not None for t in token_out) else None,
        'reported_cost_per_document': str(sum(c for c in costs if c is not None) / n)
        if calls and all_costs_known else None,
        'cost_basis': 'provider-reported; not independently priced' if all_costs_known else None,
        'latency_ms': {'p50': percentile(durations, 50), 'p95': percentile(durations, 95)},
        'rows': rows,
    }


def hosted_optimization(
    all_route: Mapping[str, Any], gated_route: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare measured provider usage without inventing token prices."""
    if all_route.get('status') != 'measured' or gated_route.get('status') != 'measured':
        return {'status': 'not_run', 'reason': 'hosted routes were not both measured'}

    all_calls = all_route.get('hosted_calls')
    gated_calls = gated_route.get('hosted_calls')
    if (
        isinstance(all_calls, bool)
        or not isinstance(all_calls, int)
        or isinstance(gated_calls, bool)
        or not isinstance(gated_calls, int)
    ):
        return {'status': 'not_run', 'reason': 'hosted call counts are unavailable'}

    def token_total(route: Mapping[str, Any]) -> int | None:
        prompt = route.get('prompt_tokens')
        completion = route.get('completion_tokens')
        if (
            isinstance(prompt, bool)
            or not isinstance(prompt, int)
            or isinstance(completion, bool)
            or not isinstance(completion, int)
        ):
            return None
        return prompt + completion

    all_tokens = token_total(all_route)
    gated_tokens = token_total(gated_route)
    all_cost = all_route.get('reported_cost_per_document')
    gated_cost = gated_route.get('reported_cost_per_document')
    cost_reduction: float | None = None
    if all_cost is not None and gated_cost is not None:
        try:
            all_decimal = Decimal(str(all_cost))
            gated_decimal = Decimal(str(gated_cost))
            if all_decimal > 0:
                cost_reduction = float((all_decimal - gated_decimal) / all_decimal)
        except (ValueError, ArithmeticError):
            cost_reduction = None

    return {
        'status': 'measured',
        'all_calls': all_calls,
        'gated_calls': gated_calls,
        'avoided_calls': all_calls - gated_calls,
        'call_reduction_rate': rate(all_calls - gated_calls, all_calls),
        'all_tokens': all_tokens,
        'gated_tokens': gated_tokens,
        'token_reduction_rate': (
            rate(all_tokens - gated_tokens, all_tokens)
            if all_tokens is not None and gated_tokens is not None
            else None
        ),
        'reported_cost_reduction_rate': cost_reduction,
        'cost_basis': (
            'provider-reported; no catalog price inferred'
            if cost_reduction is not None
            else None
        ),
    }


def snapshot(number: int, fields: Mapping[str, Any]) -> DeltaSnapshot:
    copied_fields = deepcopy(dict(fields))
    raw = RawRecord(id=UUID(int=100 + number), source_id=UUID(int=1),
                    source_record_id='frozen-delta', payload_json=copied_fields,
                    payload_sha256=str(number) * 64)
    version = OpportunityVersion(id=UUID(int=200 + number), opportunity_id=UUID(int=2),
                                 raw_record_id=raw.id, version_number=number,
                                 source_record_id=raw.source_record_id,
                                 effective_at=datetime(2026, 9, number, tzinfo=UTC),
                                 normalized_json=deepcopy(copied_fields),
                                 normalized_sha256=str(number) * 64)
    return DeltaSnapshot(version=version, raw=raw)


def delta_eval(cases: list[dict[str, Any]]) -> dict[str, Any]:
    predicted: set[str] = set()
    expected: set[str] = set()
    observed_high: set[str] = set()
    expected_high: set[str] = set()
    no_change = false_alerts = 0
    rows = []
    for case in cases:
        result = compute_delta(snapshot(1, case['before']), snapshot(2, case['after']))
        fields = sorted(result.field_changes_json)
        predicted.update(f"{case['id']}:{x}" for x in fields)
        expected.update(f"{case['id']}:{x}" for x in case['expected_fields'])
        if case['expected_impact'] == 'high':
            expected_high.add(case['id'])
        if result.impact_level == 'high':
            observed_high.add(case['id'])
        if not case['expected_fields']:
            no_change += 1
            false_alerts += int(bool(fields))
        rows.append({'id': case['id'], 'fields': fields, 'impact': result.impact_level,
                     'expected_fields': case['expected_fields'],
                     'expected_impact': case['expected_impact']})
    return {'cases': len(cases), 'fields': set_metrics(predicted, expected),
            'high_impact': set_metrics(observed_high, expected_high),
            'false_alert_rate': rate(false_alerts, no_change), 'no_change_support': no_change,
            'rows': rows}


def link_eval(cases: list[dict[str, Any]]) -> dict[str, Any]:
    def candidate(raw: dict[str, Any]) -> LinkCandidate:
        return LinkCandidate(
            opportunity_id=UUID(int=raw['id']), source_id=UUID(int=raw['source_id']),
            source_record_id=raw['record_id'], lifecycle_stage=raw['stage'],
            title=raw['title'], buyer_name=raw['buyer'], estimated_amount=Decimal(raw['amount']),
            published_at=instant(raw['published_at']),
            official_references=tuple((UUID(int=s), record, stage)
                                      for s, record, stage in raw.get('references', [])),
        )
    expected: set[str] = set()
    predicted: set[str] = set()
    rows = []
    for case in cases:
        result = link_candidate(candidate(case['record']),
            [candidate(x) for x in case['candidates']])
        parent = result.parent_opportunity_id.int if result.parent_opportunity_id else None
        if parent is not None:
            predicted.add(f"{case['id']}:{parent}")
        if case['expected_parent_id'] is not None:
            expected.add(f"{case['id']}:{case['expected_parent_id']}")
        rows.append({'id': case['id'], 'parent': parent,
            'expected_parent': case['expected_parent_id'],
                     'status': result.status, 'reason': result.reason})
    return {'cases': len(cases), 'links': set_metrics(predicted, expected), 'rows': rows}


async def run_evaluation(root: Path, *, with_ocr: bool = False,
                         hosted: StructuredExtractor | None = None) -> dict[str, Any]:
    data, dataset_hash = load_dataset(root / 'data/eval')
    start = time.perf_counter()
    replay = data['replay']
    replay_rows = []
    predicted: set[str] = set()
    expected: set[str] = set()
    for i, query in enumerate(replay['queries']):
        result = replay_at(replay['events'], replay['profiles'], instant(query['as_of']))
        result['metrics'] = ranking_metrics(result['ranked_ids'], query['relevance'], k=query['k'])
        result['expected_allowed'] = query['expected_allowed']
        predicted.update(f'{i}:{item}' for item in result['ranked_ids'])
        expected.update(f'{i}:{item}' for item in query['expected_allowed'])
        replay_rows.append(result)
    eligible = set_metrics(predicted, expected)
    hard_negative_support = sum(
        len(r['decisions']) - len(r['expected_allowed']) for r in replay_rows
    )
    routes: dict[str, Any] = {
        'deterministic': await extraction_eval(data['extraction_cases'], DeterministicExtractor()),
        'hosted_all': {'status': 'not_run', 'reason': 'explicit hosted opt-in not supplied',
            'metrics': None},
        'hosted_gated': {'status': 'not_run', 'reason': 'explicit hosted opt-in not supplied',
            'metrics': None},
    }
    optimization: dict[str, Any] = {
        'status': 'not_run',
        'reason': 'hosted routes were not both measured',
    }
    if hosted is not None:
        routes['hosted_all'] = await extraction_eval(data['extraction_cases'], hosted)
        routes['hosted_gated'] = await extraction_eval(data['extraction_cases'], hosted, gated=True)
        optimization = hosted_optimization(routes['hosted_all'], routes['hosted_gated'])
    ocr: dict[str, Any] = {'status': 'not_run', 'field_accuracy': None,
                           'reason': (
                               'real OCR opt-in not supplied; fixture fake is never scored as OCR'
                           )}
    if with_ocr:
        from .ocr import evaluate_ocr
        ocr = await evaluate_ocr(root / 'data/eval')
    return {
        'schema_version': 1, 'created_at': datetime.now(UTC).isoformat(),
        'provenance': provenance(root, dataset_hash, {'with_ocr': with_ocr,
            'hosted': hosted is not None}),
        'dataset_version': data['dataset_version'], 'public_real_records': 0,
        'extraction_routes': routes, 'hosted_optimization': optimization, 'ocr': ocr,
        'lifecycle': link_eval(data['link_cases']), 'delta': delta_eval(data['delta_cases']),
        'eligibility': {**eligible, 'false_positive_hard_eligibility_rate':
                        rate(int(eligible['fp'] or 0), hard_negative_support),
                        'hard_negative_support': hard_negative_support},
        'historical_replay': replay_rows,
        'total_elapsed_ms': (time.perf_counter() - start) * 1000,
        'limitations': [
            'Tiny hand-authored synthetic regression set, not unseen real procurement data.',
            ('Labels authored for this system, so these are smoke/regression scores, '
             'not generalization.'),
            'Outcome labels are not features and do not independently prove company suitability.',
            'Local OCR benchmark is separate from the default service fixture-fake OCR adapter.',
            ('Hosted route timings include provider network and retries; other timings exclude '
             'live network, PostgreSQL, Redis and end-user request latency.'),
        ],
    }
