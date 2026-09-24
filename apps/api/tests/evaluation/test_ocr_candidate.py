from __future__ import annotations

import asyncio
import hashlib
import json
import os
import runpy
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from app.evaluation import ocr_candidate

PRIVATE = "Private full OCR material must not be published"


def source(directory, name):
    raw = b"%PDF-1.7 test source " + name.encode()
    (directory / f"{name}.pdf").write_bytes(raw)
    return {"id": name, "filename": f"{name}.pdf", "page": 1,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "expected_fields": {"title": "Project", "buyer_name": "Agency",
                                "procurement_type": "services"},
            "recognition_anchors": {"title": "Project"}}


def reply(text, page=1):
    return json.dumps({"page_number": page, "text": text,
                       "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                       "peak_rss_kib": 600000}).encode()


def test_candidate_scores_same_validator_and_never_publishes_text(tmp_path, monkeypatch):
    sources = [source(tmp_path, name) for name in ("valid", "partial")]
    texts = ["Title: Project\nBuyer: Agency\nCategory: services\n" + PRIVATE, "Title: Project"]

    async def run(args, *, timeout):
        assert timeout == 40
        assert args[-1] in {item["sha256"] for item in sources}
        return reply(texts.pop(0))

    monkeypatch.setattr(ocr_candidate, "run_ocr_process", run)
    result = asyncio.run(ocr_candidate.evaluate_candidate(
        {"sources": sources}, tmp_path, Path("python"), Path("models"),
    ))
    assert result["summary"]["expected_fields"] == 6
    assert result["summary"]["trusted_correct_fields"] == 3
    assert result["rows"][1]["rejection_stage"] == "schema"
    assert PRIVATE not in json.dumps(result)
    assert "Title: Project" not in json.dumps(result)


@pytest.mark.parametrize("bad", [b"not-json", reply("private", 2),
                                  reply("private").replace(b"private", b"changed"),
                                  b'{"error":"private source text"}'])
def test_invalid_reply_keeps_denominator_without_partial_success(tmp_path, monkeypatch, bad):
    sources = [source(tmp_path, name) for name in ("a", "b")]
    outputs = [reply("Title: Project\nBuyer: Agency\nCategory: services"), bad]

    async def run(*args, **kwargs):
        return outputs.pop(0)

    monkeypatch.setattr(ocr_candidate, "run_ocr_process", run)
    result = asyncio.run(ocr_candidate.evaluate_candidate(
        {"sources": sources}, tmp_path, Path("python"), Path("models"),
    ))
    assert result["summary"]["status"] == "incomplete"
    assert result["summary"]["expected_fields"] == 6
    assert result["summary"]["expected_anchors"] == 2
    assert result["summary"]["trusted_field_accuracy"] is None
    assert result["rows"][1]["status"] == "failed"
    assert "private" not in json.dumps(result)


def test_all_hashes_checked_before_any_candidate_process(tmp_path, monkeypatch):
    sources = [source(tmp_path, name) for name in ("a", "b")]
    (tmp_path / "b.pdf").write_bytes(b"changed")

    async def unexpected(*args, **kwargs):
        pytest.fail("recognition started before source preflight")

    monkeypatch.setattr(ocr_candidate, "run_ocr_process", unexpected)
    with pytest.raises(ValueError, match="checksum"):
        asyncio.run(ocr_candidate.evaluate_candidate(
            {"sources": sources}, tmp_path, Path("python"), Path("models"),
        ))


def test_real_child_preserves_the_selected_virtual_environment(tmp_path, monkeypatch):
    environment = tmp_path / "candidate-env"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    script = tmp_path / "scripts/rapid_ocr_candidate.py"
    script.parent.mkdir()
    payload = reply("Title: Project\nBuyer: Agency\nCategory: services").decode()
    script.write_text(
        "import sys\n"
        f"print({payload!r} if sys.prefix == {str(environment)!r} else '{{}}')\n"
    )
    monkeypatch.setattr(ocr_candidate, "ROOT", tmp_path)
    result = asyncio.run(ocr_candidate.evaluate_candidate(
        {"sources": [source(tmp_path, "original")]}, tmp_path,
        environment / "bin/python", Path("models"),
    ))
    assert result["summary"]["status"] == "measured"
    assert result["summary"]["trusted_correct_fields"] == 3


def test_cli_unavailable_candidate_keeps_all_cases_and_writes_failed_artifact(tmp_path):
    environment = tmp_path / "unavailable-env"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    sources = [source(tmp_path, name) for name in ("a", "b")]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"suite": "test-suite", "sources": sources,
                                   "source_kind": "public_pdf_with_native_text",
                                   "selection": "generated test cases"}))
    root = Path(__file__).resolve().parents[4]
    output = tmp_path / "result.json"
    result = subprocess.run([
        sys.executable, str(root / "scripts/run_ocr_candidate_eval.py"),
        "--source-dir", str(tmp_path), "--manifest", str(manifest),
        "--candidate-python", str(environment / "bin/python"),
        "--models", str(tmp_path), "--output", str(output),
    ], capture_output=True, timeout=10, check=False,
        env={**os.environ, "PYTHONPATH": str(root / "apps/api")})
    assert result.returncode != 0
    assert output.exists()
    measured = json.loads(output.read_text())["groups"][0]["measurement"]
    assert measured["summary"]["status"] == "incomplete"
    assert measured["summary"]["expected_fields"] == 6
    assert measured["summary"]["expected_anchors"] == 2
    assert measured["summary"]["trusted_field_accuracy"] is None
    assert all(row["reason"] == "probe_failed" for row in measured["rows"])


def test_colliding_suite_names_cannot_hide_an_incomplete_group(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[4] / "scripts/run_ocr_candidate_eval.py"
    module = runpy.run_path(str(script))
    result = {"groups": [
        {"suite": "same", "measurement": {"summary": {"status": status}}}
        for status in ("incomplete", "measured")
    ]}
    monkeypatch.setitem(module["main"].__globals__, "evaluate", lambda args: result)
    monkeypatch.setattr(asyncio, "run", lambda value: value)
    monkeypatch.setattr(sys, "argv", [
        str(script), "--source-dir", ".", "--models", ".", "--candidate-python", "python",
        "--manifest", "test.json", "--output", str(tmp_path / "result.json"),
    ])
    with pytest.raises(SystemExit, match="incomplete"):
        module["main"]()
