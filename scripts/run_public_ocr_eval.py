"""Run public-document diagnostics on explicitly supplied, checksum-pinned PDFs."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import PIL
import pymupdf

from app.evaluation.provenance import provenance
from app.evaluation.public_documents import evaluate_public_documents
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.validation import GROUNDING_VERSION

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--tessdata-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "data/eval/public_ocr_manifest.json")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "artifacts/evaluation/public-ocr.json")
    args = parser.parse_args()
    tessdata = args.tessdata_dir.resolve()
    model_hashes = {
        name: hashlib.sha256((tessdata / f"{name}.traineddata").read_bytes()).hexdigest()
        for name in ("kor", "eng")
    }
    os.environ["TESSDATA_PREFIX"] = str(tessdata)
    raw_manifest = args.manifest.read_bytes()
    manifest = json.loads(raw_manifest)
    metadata = provenance(ROOT, hashlib.sha256(raw_manifest).hexdigest(), {
        "language": "kor+eng", "page_segmentation_mode": 3,
        "preparation": manifest["preparation"], "tessdata_sha256": model_hashes,
        "pymupdf": pymupdf.VersionBind, "pillow": PIL.__version__,
        "extractor_version": DeterministicExtractor.extractor_version,
        "grounding_version": GROUNDING_VERSION,
    })
    metadata["synthetic"] = False
    result = {
        "schema_version": 1, "suite": manifest["suite"],
        "measured_at": datetime.now(UTC).isoformat(),
        "provenance": metadata,
        "source_kind": manifest["source_kind"], "natural_scan_documents": 0,
        "public_source_documents": len(manifest["sources"]),
        "selection": manifest["selection"],
        "limitation": (
            "Public PDFs, one page each, rasterized into three correlated variants. "
            "Not natural scans, a representative corpus, full-page CER, or production OCR. "
            "Anchors use NFC and whitespace-insensitive exact substring matching. "
            "Trusted fields require the versioned production validator to accept the whole result. "
            "Raw source PDFs, full native text and OCR output are not published."
        ),
        "measurement": asyncio.run(evaluate_public_documents(manifest, args.source_dir)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
                           + "\n", encoding="utf-8")
    summary = result["measurement"]["ocr"]["summary"]
    print(json.dumps(summary, ensure_ascii=False))
    if summary["status"] != "measured":
        raise SystemExit("Public OCR incomplete; inspect per-case status, no score claimed")


if __name__ == "__main__":
    main()
