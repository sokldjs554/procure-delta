from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


def test_candidate_child_rejects_unverified_inputs_without_leaking_names(tmp_path):
    script = Path(__file__).resolve().parents[4] / "scripts/rapid_ocr_candidate.py"
    # Optional inference packages are intentionally absent from the normal API env.
    result = subprocess.run([
        sys.executable, str(script), "--models", str(tmp_path), "--pdf",
        str(tmp_path / "private-document-name.pdf"), "--page", "1",
        "--source-sha256", "a" * 64,
    ], capture_output=True, timeout=5, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"error": "candidate_failed"}
    assert b"private-document-name" not in result.stdout + result.stderr


def test_tampered_model_is_rejected_before_optional_inference_import(tmp_path):
    script = Path(__file__).resolve().parents[4] / "scripts/rapid_ocr_candidate.py"
    module = runpy.run_path(str(script))
    name = next(iter(module["MODEL_SHA256"]))
    (tmp_path / name).write_bytes(b"tampered model")
    with pytest.raises(ValueError, match="unverified model"):
        module["model_paths"](tmp_path)
