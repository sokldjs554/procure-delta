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
