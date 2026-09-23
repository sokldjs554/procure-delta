from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


@pytest.mark.parametrize("exit_code", [0, 23])
def test_real_validation_step_preserves_validator_exit_code_with_tee(tmp_path, exit_code) -> None:
    job = yaml.safe_load(WORKFLOW)["jobs"]["hosted-evaluation"]
    step = next(s for s in job["steps"] if s.get("name") == "Validate measured hosted metrics")
    # Execute the actual workflow command using GitHub's shell selection semantics.
    # No hosted call or credential is involved in this regression.
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/validate_hosted_eval.py").write_text(
        f"raise SystemExit({exit_code})\n", encoding="utf-8"
    )
    (tmp_path / "artifacts/evaluation").mkdir(parents=True)
    command = tmp_path / "step.sh"
    command.write_text(step["run"], encoding="utf-8")
    shell = step.get("shell", job.get("defaults", {}).get("run", {}).get("shell"))
    args = ["bash", "--noprofile", "--norc", "-e"]
    if shell == "bash":
        args += ["-o", "pipefail"]
    elif shell is not None:
        raise AssertionError(f"test must model the configured shell: {shell}")
    result = subprocess.run(
        [*args, str(command)], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath},
    )
    assert result.returncode == exit_code, "tee must preserve validator success and failure"
