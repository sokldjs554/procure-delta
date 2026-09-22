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


def test_provider_contract_missing_artifact_stays_not_run(tmp_path):
    from app.evaluation.summary import read_provider_contract

    all_route, gated_route, optimization = read_provider_contract(
        tmp_path / "provider-contract.json"
    )

    assert all_route.status == "not_run"
    assert gated_route.status == "not_run"
    assert optimization.status == "not_run"


def test_provider_contract_projection_separates_stub_from_model_quality(tmp_path):
    import json

    from app.evaluation.summary import read_provider_contract

    artifact = {
        "schema_version": 1,
        "synthetic": True,
        "model_quality_measured": False,
        "external_network": False,
        "routes": {
            "all": {
                "status": "measured",
                "expected_fields": 30,
                "field_accuracy": 1.0,
                "schema_failures": 4,
                "grounded_acceptance_rate": 0.5,
                "latency_ms": {"p50": 1.0, "p95": 2.0},
                "hosted_calls": 10,
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "reported_cost_per_document": None,
            },
            "gated": {
                "status": "measured",
                "expected_fields": 30,
                "field_accuracy": 1.0,
                "schema_failures": 4,
                "grounded_acceptance_rate": 0.5,
                "latency_ms": {"p50": 1.0, "p95": 2.0},
                "hosted_calls": 5,
                "prompt_tokens": 500,
                "completion_tokens": 100,
                "reported_cost_per_document": None,
            },
        },
        "optimization": {
            "status": "measured",
            "all_calls": 10,
            "gated_calls": 5,
            "avoided_calls": 5,
            "call_reduction_rate": 0.5,
            "all_tokens": 1200,
            "gated_tokens": 600,
            "token_reduction_rate": 0.5,
            "reported_cost_reduction_rate": None,
            "cost_basis": None,
        },
        "limitation": "HTTP provider stub only; external model quality was not measured.",
    }
    path = tmp_path / "provider-contract.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    all_route, gated_route, optimization = read_provider_contract(path)

    assert all_route.status == "measured"
    assert all_route.hosted_calls == 10
    assert all_route.prompt_tokens == 1000
    assert gated_route.hosted_calls == 5
    assert gated_route.prompt_tokens == 500
    assert all_route.reported_cost is None
    assert optimization.call_reduction_rate == 0.5
    assert optimization.token_reduction_rate == 0.5
    assert optimization.reported_cost_reduction_rate is None
    assert "external model quality" in (optimization.notice or "")


def test_committed_provider_contract_projection_is_measured_without_billing_claims():
    from app.evaluation.summary import read_provider_contract

    root = Path(__file__).resolve().parents[2] / "app/evaluation/results"
    all_route, gated_route, optimization = read_provider_contract(
        root / "provider-contract.json"
    )

    assert all_route.status == "measured"
    assert gated_route.status == "measured"
    assert all_route.hosted_calls == 10
    assert gated_route.hosted_calls == 5
    assert all_route.prompt_tokens == 1000
    assert gated_route.prompt_tokens == 500
    assert all_route.reported_cost is None
    assert gated_route.reported_cost is None
    assert optimization.call_reduction_rate == 0.5
    assert optimization.token_reduction_rate == 0.5
    assert optimization.reported_cost_reduction_rate is None
    assert "external LLM accuracy" in (optimization.notice or "")
