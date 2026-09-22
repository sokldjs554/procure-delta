from pathlib import Path


def test_absent_evaluation_is_not_a_perfect_score(tmp_path):
    from app.evaluation.summary import read_summary
    result = read_summary(tmp_path / 'missing.json')
    assert result.status == 'not_run'
    assert result.extraction_accuracy is None
    assert result.ocr_accuracy is None


def test_summary_uses_committed_measures_without_exposing_raw_predictions():
    from app.evaluation.summary import read_summary
    root = Path(__file__).resolve().parents[4]
    summary = read_summary(root / 'artifacts/evaluation/local.json')
    assert summary.status == 'measured'
    assert summary.synthetic is True
    assert summary.extraction_support == 30
    assert summary.ocr_correct == 17 and summary.ocr_support == 18
    assert 'recognition_text' not in summary.model_dump_json()
    assert summary.public_real_records == 0


def test_summary_exposes_route_comparison_without_inventing_hosted_metrics():
    from app.evaluation.summary import read_summary
    root = Path(__file__).resolve().parents[4]
    summary = read_summary(root / 'artifacts/evaluation/local.json')

    assert set(summary.routes) == {'deterministic', 'hosted_all', 'hosted_gated', 'ocr'}
    assert summary.routes['deterministic'].status == 'measured'
    assert summary.routes['deterministic'].support == 30
    assert summary.routes['deterministic'].field_accuracy == 1.0
    assert summary.routes['deterministic'].schema_failures == 4
    assert summary.routes['deterministic'].hosted_calls == 0

    assert summary.routes['hosted_all'].status == 'not_run'
    assert summary.routes['hosted_all'].field_accuracy is None
    assert summary.routes['hosted_all'].reported_cost is None

    assert summary.routes['hosted_gated'].status == 'not_run'
    assert summary.routes['ocr'].status == 'measured'
    assert summary.routes['ocr'].support == 18
    assert summary.routes['ocr'].field_accuracy == 17 / 18


def test_measured_hosted_route_uses_direct_metrics_shape():
    from app.evaluation.summary import _hosted_route

    route = _hosted_route({
        'status': 'measured',
        'expected_fields': 12,
        'field_accuracy': 0.75,
        'schema_failures': 1,
        'grounded_acceptance_rate': 0.8,
        'latency_ms': {'p50': 120.0, 'p95': 300.0},
        'hosted_calls': 4,
        'prompt_tokens': 80,
        'completion_tokens': 20,
        'reported_cost_per_document': '0.015',
    })

    assert route.status == 'measured'
    assert route.support == 12
    assert route.field_accuracy == 0.75
    assert route.hosted_calls == 4
    assert route.prompt_tokens == 80
    assert route.completion_tokens == 20
    assert route.reported_cost == 0.015


def test_committed_korean_ocr_artifact_is_projected_without_raw_text():
    from app.evaluation.summary import read_korean_ocr_route

    root = Path(__file__).resolve().parents[2] / "app/evaluation/results"
    route = read_korean_ocr_route(root / "korean-ocr.json")

    assert route.status == "measured"
    assert route.support == 18
    assert route.field_accuracy == 1.0
    assert route.language == "kor+eng"
    assert route.hosted_calls == 1
    assert "recognition_text" not in route.model_dump_json()
