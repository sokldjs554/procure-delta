from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[4]


def test_frozen_fixture_hash_tamper_is_detected(tmp_path):
    from app.evaluation.provenance import load_dataset
    (tmp_path / 'manifest.json').write_text(json.dumps({'files': {'benchmark.json': '0' * 64}}))
    (tmp_path / 'benchmark.json').write_text('{}')
    with pytest.raises(ValueError, match='checksum'):
        load_dataset(tmp_path)


def test_default_evaluation_calls_production_and_marks_hosted_unrun():
    from app.evaluation.runner import run_evaluation
    result = asyncio.run(run_evaluation(ROOT))
    assert result['extraction_routes']['deterministic']['documents'] == 10
    assert result['extraction_routes']['deterministic']['schema_failures'] > 0
    assert result['extraction_routes']['hosted_all']['metrics'] is None
    assert result['extraction_routes']['hosted_gated']['status'] == 'not_run'
    assert result['public_real_records'] == 0
    assert result['ocr']['field_accuracy'] is None
    assert all(not x['outcome_features_used'] for x in result['historical_replay'])


def test_ocr_page_count_mismatch_is_not_silently_dropped():
    assert importlib.util.find_spec('app.evaluation.ocr'), 'real OCR evaluation is missing'
    module = importlib.import_module('app.evaluation.ocr')
    with pytest.raises(ValueError, match='page count'):
        module.split_pages('one page\f', 3)
    assert module.split_pages('one\ftwo\f', 2) == ['one', 'two']


def test_gated_hosted_usage_counts_only_actual_provider_calls():
    import asyncio
    from decimal import Decimal

    from app.evaluation.runner import extraction_eval
    from app.extraction.deterministic import DeterministicExtractor
    from app.extraction.schemas import ExtractionResult

    class MeteredExtractor:
        provider = 'test-provider'
        model = 'test-model'
        extractor_version = 'test-v1'
        calls = 0

        async def extract(self, document):
            self.calls += 1
            result = await DeterministicExtractor().extract(document)
            return ExtractionResult(output=result.output, prompt_tokens=3, completion_tokens=5,
                                    estimated_cost=Decimal('0.10'))

    extractor = MeteredExtractor()
    cases = [
        {'id': 'valid', 'text': 'Title: Example\nBuyer: Example Agency\nCategory: services',
         'expected_valid': True, 'expected_fields': {'title': 'Example',
             'buyer_name': 'Example Agency', 'procurement_type': 'services'}},
        {'id': 'invalid', 'text': 'Unsupported prose with no required fields.',
         'expected_valid': False, 'expected_fields': {}},
    ]
    result = asyncio.run(extraction_eval(cases, extractor, gated=True))
    assert result['hosted_calls'] == extractor.calls == 1
    assert result['prompt_tokens'] == 3
    assert result['completion_tokens'] == 5
    assert Decimal(result['reported_cost_per_document']) == Decimal('0.05')
