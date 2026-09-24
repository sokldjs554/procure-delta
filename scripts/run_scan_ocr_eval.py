"""Measure checksum-pinned original public scans with the configured worker OCR adapter."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pymupdf
from app.documents.ocr_runtime import (
    PROCESS_MEMORY_BYTES,
    RUNTIME_ADAPTER_VERSION,
    RuntimeOcrConfig,
)
from app.evaluation.provenance import provenance
from app.evaluation.scan_documents import evaluate_scans
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.validation import GROUNDING_VERSION

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--tessdata-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "data/eval/public_scan_manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw_manifest = args.manifest.read_bytes()
    manifest = json.loads(raw_manifest)
    config = RuntimeOcrConfig(tessdata_dir=args.tessdata_dir.resolve())
    models = {language: hashlib.sha256(
        (config.tessdata_dir / f"{language}.traineddata").read_bytes(),
    ).hexdigest() for language in config.language.split("+")}
    metadata = provenance(ROOT, hashlib.sha256(raw_manifest).hexdigest(), {
        **config.model_dump(mode="json", exclude={"tessdata_dir"}),
        "tessdata_sha256": models, "pymupdf": pymupdf.VersionBind,
        "mupdf": pymupdf.VersionFitz,
        "adapter_version": RUNTIME_ADAPTER_VERSION,
        "process_memory_bytes": PROCESS_MEMORY_BYTES,
        "extractor_version": DeterministicExtractor.extractor_version,
        "grounding_version": GROUNDING_VERSION,
    })
    metadata["synthetic"] = False
    result = {
        "schema_version": 1, "suite": manifest["suite"],
        "measured_at": datetime.now(UTC).isoformat(), "provenance": metadata,
        "source_kind": manifest["source_kind"], "selection": manifest["selection"],
        "measurement": asyncio.run(evaluate_scans(manifest, args.source_dir, config)),
        "limitation": (
            "Original image-only PDFs; no page rewriting, rerasterization, blur or crop before "
            "the worker adapter. All pages requested for recognition; only pre-annotated "
            "pages scored when recognition completes. "
            "Field validation is page-scoped, not full-PDF worker extraction acceptance. "
            "Elapsed time covers whole-PDF recognition, excluding the startup probe and scoring. "
            "Small convenience sample, not a representative/independently annotated corpus, "
            "full-page CER, hosted-LLM evaluation, worker DB persistence or cloud throughput. "
            "Source PDFs and recognized text are not published."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
                           + "\n", encoding="utf-8")
    summary = result["measurement"]["runtime"]["summary"]
    print(json.dumps(summary, ensure_ascii=False))
    if summary["status"] != "measured":
        raise SystemExit("Scan OCR incomplete; inspect per-case status, no success score claimed")


if __name__ == "__main__":
    main()
