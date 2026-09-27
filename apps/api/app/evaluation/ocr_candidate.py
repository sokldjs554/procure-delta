"""Offline candidate measurements; never selected by production OCR routing."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.documents.ocr_runtime import MAX_TEXT_CHARS, run_ocr_process

from .ocr import score_text
from .public_documents import anchor_metrics, summary, verified_sources

ROOT = Path(__file__).resolve().parents[4]


class CandidateReply(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    page_number: int = Field(ge=1, le=50)
    text: str = Field(max_length=MAX_TEXT_CHARS)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    peak_rss_kib: int = Field(ge=0, le=1024 * 1024)


class CandidateFailureReply(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    error: Literal["candidate_failed"]
    stage: Literal["environment", "models", "source", "render", "initialization",
                   "inference", "detection", "recognition", "output", "unknown"]
    code: Literal["memory_allocation", "invalid_input", "dependency_unavailable", "runtime_error"]


CANDIDATE_REPLY: TypeAdapter[CandidateReply | CandidateFailureReply] = TypeAdapter(
    CandidateReply | CandidateFailureReply,
)


async def evaluate_candidate(
    manifest: dict[str, Any], directory: Path, python: Path, models: Path,
    *, probe_failed: bool = False,
) -> dict[str, Any]:
    sources = verified_sources(manifest, directory)
    rows: list[dict[str, Any]] = []
    for source, _ in sources:
        row: dict[str, Any] = {"id": source["id"], "status": "failed",
                               "scored_page": source["page"]}
        if probe_failed:
            row.update(reason="probe_failed", elapsed_ms=None)
            rows.append(row)
            continue
        started = time.perf_counter()
        failure_stage = "process"
        try:
            raw = await run_ocr_process([
                # Resolving the venv's interpreter symlink selects the base Python.
                str(python.absolute()), str(ROOT / "scripts/rapid_ocr_candidate.py"),
                "--models", str(models.resolve()), "--pdf",
                str((directory / source["filename"]).resolve()),
                "--page", str(source["page"]), "--source-sha256", source["sha256"],
            ], timeout=40)
            failure_stage = "reply"
            result = CANDIDATE_REPLY.validate_json(raw)
            if isinstance(result, CandidateFailureReply):
                row.update(error_type="CandidateFailure", failure_stage=result.stage,
                           failure_code=result.code)
            else:
                if (result.page_number != source["page"]
                        or result.text_sha256 != hashlib.sha256(result.text.encode()).hexdigest()):
                    raise ValueError("candidate provenance mismatch")
                failure_stage = "scoring"
                row.update({
                    "status": "measured", "text_sha256": result.text_sha256,
                    "peak_rss_kib": result.peak_rss_kib, "characters": len(result.text),
                    "anchors": anchor_metrics(result.text, source["recognition_anchors"]),
                    **await score_text(result.text, source["expected_fields"]),
                })
        except (ValueError, OSError, RuntimeError, TimeoutError) as error:
            # No child output, OCR values or exception messages in published evidence.
            code = ("timeout" if isinstance(error, TimeoutError) else
                    "invalid_reply" if failure_stage == "reply" else "runtime_error")
            row.update(error_type=type(error).__name__, failure_stage=failure_stage,
                       failure_code=code)
        row["elapsed_ms"] = (time.perf_counter() - started) * 1000
        rows.append(row)
    aggregate = summary(rows)
    aggregate["expected_fields"] = sum(len(source["expected_fields"]) for source, _ in sources)
    aggregate["expected_anchors"] = sum(len(source["recognition_anchors"]) for source, _ in sources)
    return {"summary": aggregate, "rows": rows}
