"""Small allowlisted public projection of a committed, offline evaluation artifact."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class EvaluationSummary(BaseModel):
    status: Literal['measured', 'not_run'] = 'not_run'
    synthetic: bool = True
    public_real_records: int = 0
    measured_at: str | None = None
    dataset_version: str | None = None
    dataset_sha256: str | None = None
    source_sha256: str | None = None
    extraction_accuracy: float | None = None
    extraction_correct: int = 0
    extraction_support: int = 0
    delta_precision: float | None = None
    delta_recall: float | None = None
    delta_support: int = 0
    lifecycle_precision: float | None = None
    lifecycle_resolved: int = 0
    lifecycle_cases: int = 0
    replay_queries: int = 0
    ocr_accuracy: float | None = None
    ocr_correct: int = 0
    ocr_support: int = 0
    ocr_language: str | None = None
    hosted_evaluated: bool = False
    notice: str = ('저장된 소규모 합성 회귀 평가입니다. 현재 운영 지표나 '
                   '실제 조달 데이터·한국어 스캔·LLM 품질 성적이 아닙니다.')


def read_summary(path: Path) -> EvaluationSummary:
    if not path.exists():
        return EvaluationSummary()
    raw = json.loads(path.read_text(encoding='utf-8'))
    if raw.get('schema_version') != '1' and raw.get('schema_version') != 1:
        raise ValueError('unknown evaluation artifact schema')
    source = raw['provenance']
    if source.get('synthetic') is not True:
        raise ValueError('this public regression panel only accepts labeled synthetic artifacts')
    extraction = raw['extraction_routes']['deterministic']
    delta, lifecycle, ocr = raw['delta'], raw['lifecycle'], raw['ocr']
    return EvaluationSummary(
        status='measured', measured_at=raw['created_at'], dataset_version=raw['dataset_version'],
        public_real_records=raw['public_real_records'],
        dataset_sha256=source['dataset_sha256'], source_sha256=source['source_sha256'],
        extraction_accuracy=extraction['field_accuracy'],
        extraction_correct=extraction['correct_fields'],
            extraction_support=extraction['expected_fields'],
        delta_precision=delta['fields']['precision'], delta_recall=delta['fields']['recall'],
        delta_support=delta['fields']['expected_support'],
        lifecycle_precision=lifecycle['links']['precision'],
        lifecycle_resolved=lifecycle['links']['predicted_support'],
            lifecycle_cases=lifecycle['cases'],
        replay_queries=len(raw['historical_replay']),
        ocr_accuracy=ocr.get('field_accuracy'), ocr_correct=ocr.get('correct_fields', 0),
        ocr_support=ocr.get('expected_fields', 0), ocr_language=ocr.get('language'),
        hosted_evaluated=raw['extraction_routes']['hosted_all'].get('status') == 'measured',
    )
