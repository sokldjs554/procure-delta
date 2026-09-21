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
