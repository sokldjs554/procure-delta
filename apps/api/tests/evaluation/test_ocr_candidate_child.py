from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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
    assert json.loads(result.stdout) == {
        "error": "candidate_failed", "stage": "environment", "code": "dependency_unavailable",
    }
    assert b"private-document-name" not in result.stdout + result.stderr


def test_tampered_model_is_rejected_before_optional_inference_import(tmp_path):
    script = Path(__file__).resolve().parents[4] / "scripts/rapid_ocr_candidate.py"
    module = runpy.run_path(str(script))
    name = next(iter(module["MODEL_SHA256"]))
    (tmp_path / name).write_bytes(b"tampered model")
    with pytest.raises(ValueError, match="unverified model"):
        module["model_paths"](tmp_path)


@pytest.mark.parametrize(("stage", "error", "code"), [
    ("detection", MemoryError("private source"), "memory_allocation"),
    ("detection", type("ONNXRuntimeError", (Exception,), {})(
        "private source: std::bad_alloc"), "memory_allocation"),
    ("detection", RuntimeError("private detection error"), "runtime_error"),
    ("recognition", RuntimeError("private recognition error"), "runtime_error"),
    ("recognition", MemoryError("private source"), "memory_allocation"),
    ("initialization", MemoryError("private model path"), "memory_allocation"),
])
def test_child_reports_only_allowlisted_stage_and_cause(
    tmp_path, monkeypatch, capsys, stage, error, code,
):
    import hashlib

    import pymupdf

    script = Path(__file__).resolve().parents[4] / "scripts/rapid_ocr_candidate.py"
    module = runpy.run_path(str(script))
    namespace = module["main"].__globals__
    pdf = tmp_path / "private.pdf"
    with pymupdf.open() as document:
        document.new_page(width=72, height=72)
        document.save(pdf)

    class Engine:
        def __init__(self, **kwargs):
            if stage == "initialization":
                raise error
            self.text_det = self.detect
            self.text_rec = self.recognize

        def detect(self, image):
            if stage == "detection":
                raise error
            return image

        def recognize(self, image):
            raise error

        def __call__(self, image):
            assert image.startswith(b"\x89PNG")
            self.text_rec(self.text_det(image))

    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(setNumThreads=lambda _: None))
    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(
        RapidOCR=Engine, LangRec=SimpleNamespace(KOREAN="korean"),
        ModelType=SimpleNamespace(MOBILE="mobile"), OCRVersion=SimpleNamespace(PPOCRV5="v5"),
    ))
    monkeypatch.setitem(namespace, "metadata", lambda: {})
    monkeypatch.setitem(namespace, "model_paths", lambda _: {
        name: "verified-test-model" for name in module["MODEL_SHA256"]
    })
    # Keep the real script entry point and render/engine call path, without
    # lowering this pytest process's limits or changing its network functions.
    monkeypatch.setitem(namespace, "resource", SimpleNamespace(
        setrlimit=lambda *args: None, RLIMIT_AS=0, RLIMIT_CPU=1,
    ))
    monkeypatch.setitem(namespace, "socket", SimpleNamespace(socket=SimpleNamespace()))
    monkeypatch.setattr(sys, "argv", [str(script), "--models", str(tmp_path),
        "--pdf", str(pdf), "--page", "1", "--source-sha256",
        hashlib.sha256(pdf.read_bytes()).hexdigest()])
    module["main"]()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "error": "candidate_failed", "stage": stage, "code": code,
    }
    assert "private" not in captured.out + captured.err
