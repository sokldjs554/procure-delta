from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = (ROOT / ".github/workflows/hosted-eval.yml").read_text(encoding="utf-8")


def test_hosted_workflow_is_manual_secret_gated_and_never_publishes() -> None:
    assert "workflow_dispatch:" in WORKFLOW
    assert "PROCURE_DELTA_LLM_API_KEY" in WORKFLOW
    assert "--allow-hosted" in WORKFLOW
    assert "validate_hosted_eval.py" in WORKFLOW
    assert "actions/upload-artifact@v4" in WORKFLOW
    assert "--publish" not in WORKFLOW
    assert "push:" not in WORKFLOW
    assert "pull_request:" not in WORKFLOW


def test_hosted_workflow_records_provider_identity_without_committing_secret() -> None:
    for name in (
        "EXTRACTION_ENDPOINT",
        "EXTRACTION_PROVIDER",
        "EXTRACTION_MODEL",
        "EXTRACTION_MAX_COMPLETION_TOKENS",
        "EXTRACTION_API_KEY",
    ):
        assert name in WORKFLOW
    assert "credential-free HTTPS endpoint" in WORKFLOW
    assert "permissions:\n  contents: read" in WORKFLOW
