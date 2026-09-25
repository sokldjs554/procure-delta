"""Evaluate a pinned optional OCR candidate on frozen public first pages offline."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.documents.ocr_runtime import run_ocr_process
from app.evaluation.ocr_candidate import evaluate_candidate
from app.evaluation.provenance import provenance
from app.evaluation.public_documents import verified_sources
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.validation import GROUNDING_VERSION

ROOT = Path(__file__).resolve().parents[1]


async def evaluate(args):
    # Preflight every dataset before invoking even the optional package probe.
    datasets = []
    for path in args.manifest:
        raw = path.read_bytes()
        manifest = json.loads(raw)
        verified_sources(manifest, args.source_dir)
        datasets.append((manifest, hashlib.sha256(raw).hexdigest()))
    probe_failed = False
    try:
        described = await run_ocr_process([
            str(args.candidate_python.absolute()), str(ROOT / "scripts/rapid_ocr_candidate.py"),
            "--describe",
        ], timeout=5)
        config = json.loads(described)
        if (not isinstance(config, dict)
                or config.get("candidate_version") != "ppocr-v5-offline-v1"):
            raise ValueError("Candidate environment is unavailable or not pinned")
    except (ValueError, OSError, RuntimeError, TimeoutError) as error:
        probe_failed = True
        config = {"environment_status": "unavailable", "error_type": type(error).__name__}
    config.update(extractor_version=DeterministicExtractor.extractor_version,
                  grounding_version=GROUNDING_VERSION, wall_timeout_seconds=40)
    groups = []
    for manifest, digest in datasets:
        metadata = provenance(ROOT, digest, config)
        metadata["synthetic"] = False
        measurement = await evaluate_candidate(
            manifest, args.source_dir, args.candidate_python, args.models,
            probe_failed=probe_failed,
        )
        groups.append({"suite": manifest["suite"], "source_kind": manifest["source_kind"],
                       "selection": "Development regression on previously inspected pages; "
                                    "current extraction rules were informed by this corpus.",
                       "initial_selection_note": manifest["selection"],
                       "sources": manifest["sources"],
                       "provenance": metadata, "measurement": measurement})
    return {"schema_version": 1, "measured_at": datetime.now(UTC).isoformat(),
            "suite": "korean-ocr-candidate-v1", "groups": groups,
            "limitation": (
                "Development diagnostic on known convenience samples, not a holdout. "
                "One annotated page per source rendered in RGB at 300 dpi; RapidOCR then "
                "uses its version-pinned defaults including max_side_len=2000. No crops, "
                "manual corrections or label-specific preprocessing. Native PDFs are "
                "raster controls, not natural scans. Page-scoped versioned deterministic "
                "extraction and grounding; not whole-PDF recognition/worker acceptance. "
                "1 GiB address-space limit differs from the 512 MiB production worker. "
                "Elapsed time includes a cold single-page child, imports, model/source "
                "hashing, rendering, recognition and parent scoring. Not comparable with "
                "whole-PDF worker timings. RSS is Linux child high-water mark, not cloud "
                "capacity. Raw PDFs, text, values, quotes and confidences are not published. "
                "The runner does not select a production OCR backend. Initial selection "
                "notes describe corpus collection, not the current tuning/holdout status."
            )}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--candidate-python", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= len(args.manifest) <= 3:
        parser.error("Supply 1-3 frozen manifests")
    result = asyncio.run(evaluate(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
                           + "\n", encoding="utf-8")
    summaries = [{"suite": group["suite"], **group["measurement"]["summary"]}
                 for group in result["groups"]]
    print(json.dumps(summaries, ensure_ascii=False))
    if any(value["status"] != "measured" for value in summaries):
        raise SystemExit("Candidate evaluation incomplete; no partial aggregate score")


if __name__ == "__main__":
    main()
