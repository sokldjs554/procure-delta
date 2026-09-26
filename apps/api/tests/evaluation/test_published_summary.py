import hashlib
import json
import shutil
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parents[2] / "app/evaluation/results"


def test_published_hosted_measures_preserve_separate_ocr_and_provenance():
    from app.evaluation.summary import read_published_summary, read_summary

    local = read_summary(RESULTS / "local.json")
    result = read_published_summary(RESULTS)
    assert result.hosted_evaluated is True
    assert result.hosted_current_contract_evaluated is False
    assert result.routes["hosted_all"].prompt_contract_status == "unknown"
    assert result.routes["hosted_all"].prompt_contract_sha256 is None
    assert result.routes["hosted_all"].extractor_version == "chat-prompt-json-v3-a522d812a6f15e65"
    assert result.routes["hosted_all"].field_accuracy == 1
    assert result.routes["hosted_gated"].field_accuracy == 1
    assert result.hosted_optimization.all_tokens == 22343
    assert result.hosted_optimization.gated_tokens == 10149
    assert result.routes["hosted_all"].reported_cost is None
    assert result.ocr_correct == 17 and result.ocr_support == 18
    assert result.routes["ocr_korean"].field_accuracy == 1
    assert result.source_sha256 == local.source_sha256
    assert result.measured_at == local.measured_at
    assert "ae63b047" in result.routes["hosted_all"].notice
    assert "로컬 규칙" in result.routes["hosted_gated"].notice
    for private in ("trusted_fields", "response_diagnostics", "recognition_text"):
        assert private not in result.model_dump_json()


def test_no_hosted_file_keeps_unmeasured_state(tmp_path):
    from app.evaluation.summary import read_published_summary

    shutil.copy(RESULTS / "local.json", tmp_path / "local.json")
    result = read_published_summary(tmp_path)
    assert result.hosted_evaluated is False
    assert result.routes["hosted_all"].status == "not_run"
    assert result.hosted_optimization.all_tokens is None


@pytest.mark.parametrize("bad_value", ["missing_usage", "different_dataset"])
def test_invalid_hosted_evidence_cannot_replace_public_measurements(tmp_path, bad_value):
    from app.evaluation.summary import read_published_summary

    shutil.copy(RESULTS / "local.json", tmp_path / "local.json")
    raw = json.loads((RESULTS / "hosted.json").read_text())
    if bad_value == "missing_usage":
        raw["extraction_routes"]["hosted_all"]["prompt_tokens"] = None
    else:
        raw["provenance"]["dataset_sha256"] = "different"
    (tmp_path / "hosted.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        read_published_summary(tmp_path)


def test_static_demo_snapshot_matches_api_projection_and_original_artifact():
    from app.api.evaluation import summary

    root = Path(__file__).resolve().parents[4]
    original = root / "artifacts/evaluation/hosted.json"
    assert original.read_bytes() == (RESULTS / "hosted.json").read_bytes()
    text = (root / "apps/web/lib/evaluation-snapshot.ts").read_text()
    encoded = text.split("export const evaluationSnapshot: EvaluationSummary = ", 1)[1]
    assert json.loads(encoded.removesuffix(";\n")) == summary().model_dump(mode="json")


@pytest.mark.parametrize("matching", [True, False])
def test_prompt_applicability_is_separate_from_a_valid_historical_measurement(tmp_path, matching):
    from app.evaluation.summary import read_published_summary
    from app.extraction.prompt import extraction_system_prompt

    shutil.copy(RESULTS / "local.json", tmp_path / "local.json")
    raw = json.loads((RESULTS / "hosted.json").read_text())
    current_hash = hashlib.sha256(extraction_system_prompt().encode()).hexdigest()
    for name in ("hosted_all", "hosted_gated"):
        raw["extraction_routes"][name]["extractor"]["prompt_contract_sha256"] = (
            current_hash if matching else "0" * 64
        )
    (tmp_path / "hosted.json").write_text(json.dumps(raw))
    result = read_published_summary(tmp_path)
    assert result.hosted_evaluated is True
    assert result.hosted_current_contract_evaluated is matching
    for name in ("hosted_all", "hosted_gated"):
        route = result.routes[name]
        assert route.status == "measured" and route.field_accuracy == 1
        assert route.prompt_contract_status == ("current" if matching else "different")
        assert route.current_prompt_contract_sha256 == current_hash
    assert result.hosted_optimization.all_tokens == 22343
    assert result.hosted_optimization.gated_tokens == 10149
