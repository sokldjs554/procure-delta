"""Offline, checksum-pinned public PDF OCR diagnostics, separate from synthetic CI."""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image, ImageFilter

from .metrics import rate
from .ocr import evaluate_ocr, score_text

VARIANTS = (("300dpi", 300, 0.0), ("300dpi_blurred", 300, 1.2), ("150dpi", 150, 0.0))


def normalized_text(text: str) -> str:
    return "".join(unicodedata.normalize("NFC", text).split())


def anchor_metrics(text: str, anchors: dict[str, str]) -> dict[str, Any]:
    normalized = normalized_text(text)
    if not anchors or any(not normalized_text(value) for value in anchors.values()):
        raise ValueError("recognition anchors must be nonempty")
    matches = {}
    for key, value in anchors.items():
        anchor = normalized_text(value)
        # A smaller amount/date must not match inside a different, longer number.
        pattern = (r"(?<![\d,])" if anchor[0].isdigit() else "") + re.escape(anchor)
        if anchor[-1].isdigit():
            pattern += r"(?![\d,])"
        matches[key] = re.search(pattern, normalized) is not None
    return {
        "correct": sum(matches.values()), "support": len(matches),
        "recall": rate(sum(matches.values()), len(matches)), "per_anchor": matches,
    }


def verified_sources(
    manifest: dict[str, Any], directory: Path,
) -> list[tuple[dict[str, Any], bytes]]:
    sources = manifest["sources"]
    if not 1 <= len(sources) <= 3 or len({source["id"] for source in sources}) != len(sources):
        raise ValueError("public OCR requires 1-3 distinct source documents")
    result = []
    for source in sources:
        path = (directory / source["filename"]).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("public OCR source escapes source directory")
        if not 1 <= path.stat().st_size <= 10 * 1024 * 1024:
            raise ValueError("public OCR source exceeds byte budget")
        raw = path.read_bytes()
        if not raw.startswith(b"%PDF-") or hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError(f"public OCR PDF checksum mismatch: {source['id']}")
        if not source["expected_fields"]:
            raise ValueError("public OCR needs nonempty structured ground truth")
        anchor_metrics("", source["recognition_anchors"])
        result.append((source, raw))
    return result


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    measured = [row for row in rows if row["status"] == "measured"]
    if len(measured) != len(rows) or not rows:
        return {
            "status": "incomplete", "cases": len(rows), "measured_cases": len(measured),
            "recognition_anchor_recall": None, "trusted_field_accuracy": None,
        }
    anchors = sum(row["anchors"]["support"] for row in rows)
    recognized = sum(row["anchors"]["correct"] for row in rows)
    fields = sum(row["trusted_field_metrics"]["expected_fields"] for row in rows)
    trusted = sum(row["trusted_field_metrics"]["correct"] for row in rows)
    proposed = sum(row["field_metrics"]["correct"] for row in rows)
    return {
        "status": "measured", "cases": len(rows), "measured_cases": len(rows),
        "recognized_anchors": recognized, "expected_anchors": anchors,
        "recognition_anchor_recall": rate(recognized, anchors),
        "proposed_correct_fields": proposed, "trusted_correct_fields": trusted,
        "expected_fields": fields, "trusted_field_accuracy": rate(trusted, fields),
        "valid_documents": sum(row["downstream_valid"] for row in rows),
    }


async def evaluate_public_documents(manifest: dict[str, Any], directory: Path) -> dict[str, Any]:
    # Validate every source before the first OCR call; never download implicitly.
    sources = verified_sources(manifest, directory)
    native_rows: list[dict[str, Any]] = []
    ocr_rows: list[dict[str, Any]] = []
    source_rows = []
    for source, raw in sources:
        with pymupdf.open(stream=raw, filetype="pdf") as pdf:  # type: ignore[no-untyped-call]
            page_number = source["page"]
            if not 1 <= pdf.page_count <= 50 or not 1 <= page_number <= pdf.page_count:
                raise ValueError("public OCR page budget exceeded")
            page = pdf[page_number - 1]
            native = page.get_text("text")
            if len(native.strip()) < 100:
                raise ValueError("suite requires a native-text PDF, not a natural scan")
            # Bound page dimensions before allocation (300 dpi, at most 12 MP).
            if page.rect.width * page.rect.height * (300 / 72) ** 2 > 12_000_000:
                raise ValueError("public OCR render pixel budget exceeded")
            source_rows.append({
                **source, "byte_size": len(raw), "page_count": pdf.page_count,
                "native_text_characters": len(native), "native_text_layer": True,
            })
            native_rows.append({
                "id": source["id"], "status": "measured",
                "text_sha256": hashlib.sha256(native.encode()).hexdigest(),
                "anchors": anchor_metrics(native, source["recognition_anchors"]),
                **await score_text(native, source["expected_fields"]),
            })
            for name, dpi, blur in VARIANTS:
                with tempfile.TemporaryDirectory(prefix="procure-delta-public-ocr-") as temporary:
                    target = Path(temporary)
                    pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
                    image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
                    if blur:
                        image = image.filter(ImageFilter.GaussianBlur(blur))
                    image_path = target / "page.png"
                    image.save(image_path)
                    case_id = f"{source['id']}/{name}"
                    (target / "ocr_manifest.json").write_text(json.dumps({"cases": [{
                        "id": case_id, "path": "page.png", "language": "kor+eng",
                        "synthetic": False, "expected_fields": source["expected_fields"],
                    }]}, ensure_ascii=False), encoding="utf-8")
                    measured = await evaluate_ocr(target, page_segmentation_mode=3)
                    row: dict[str, Any] = {
                        "id": case_id, "status": measured["status"],
                        "dpi": dpi, "gaussian_blur_radius": blur,
                        "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                        "image_size": [image.width, image.height],
                        "provider": measured.get("provider"),
                        "elapsed_ms": measured.get("elapsed_ms"),
                    }
                    if measured["status"] == "measured":
                        result = measured["rows"][0]
                        text = result.pop("recognition_text")
                        row.update(result)
                        row["text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
                        row["anchors"] = anchor_metrics(text, source["recognition_anchors"])
                    else:
                        row["reason"] = measured["reason"]
                    ocr_rows.append(row)
    return {
        "sources": source_rows,
        "native_control": {"summary": summary(native_rows), "rows": native_rows},
        "ocr": {"summary": summary(ocr_rows), "rows": ocr_rows},
        "by_variant": {
            name: summary([row for row in ocr_rows if row["id"].endswith(f"/{name}")])
            for name, _, _ in VARIANTS
        },
    }
