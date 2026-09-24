"""Offline measurements of original image-only PDFs through the worker OCR adapter."""
from __future__ import annotations

import hashlib
import math
import time
from pathlib import Path
from typing import Any

import pymupdf

from app.documents.download import StoredAttachment
from app.documents.ocr import OcrDocument
from app.documents.ocr_runtime import RuntimeOcrConfig, TesseractOcrAdapter
from app.documents.parsers import parse_document
from app.documents.quality import assess_text_quality

from .ocr import score_text
from .public_documents import anchor_metrics, summary, verified_sources

MAX_INSPECTION_IMAGE_PIXELS = 40_000_000


def scan_inputs(
    manifest: dict[str, Any], directory: Path, config: RuntimeOcrConfig,
) -> list[tuple[dict[str, Any], OcrDocument]]:
    if manifest.get("source_kind") != "image_only_public_pdf":
        raise ValueError("explicit image-only source provenance is required")
    inputs = []
    # Hash every source before inspecting or recognizing any PDF.
    for source, raw in verified_sources(manifest, directory):
        with pymupdf.open(stream=raw, filetype="pdf") as pdf:  # type: ignore[no-untyped-call]
            scored_page = source["page"]
            if (pdf.needs_pass or not 1 <= pdf.page_count <= config.max_pages
                    or type(scored_page) is not int or not 1 <= scored_page <= pdf.page_count):
                raise ValueError("scan page budget or annotation page is invalid")
            characters, coverage, contrast = [], [], []
            for page in pdf:
                width = math.ceil(page.rect.width * config.dpi / 72)
                height = math.ceil(page.rect.height * config.dpi / 72)
                if width < 1 or height < 1 or width * height > config.max_pixels_per_page:
                    raise ValueError("scan pixel budget exceeded")
                characters.append(len(page.get_text("text").strip()))
                images = page.get_image_info()
                if (page.get_drawings() or page.first_annot is not None
                        or sum(item["width"] * item["height"] for item in images)
                        > MAX_INSPECTION_IMAGE_PIXELS):
                    raise ValueError("scan contains overlays or exceeds image decode budget")
                # Require a full-page raster, not a blank/vector/native-text PDF.
                covered = max((
                    (pymupdf.Rect(item["bbox"]) & page.rect).get_area()  # type: ignore[no-untyped-call]
                    / page.rect.get_area()
                    for item in images
                ), default=0.0)
                coverage.append(round(covered, 6))
                if characters[-1] or covered < 0.95:
                    raise ValueError("every scan page must be image-only with full-page raster")
                # Small inspection render only; the unmodified PDF goes to the adapter.
                pixels = page.get_pixmap(dpi=36, colorspace=pymupdf.csGRAY, alpha=False).samples
                contrast.append(max(pixels) - min(pixels))
                if not contrast[-1]:
                    raise ValueError("uniform raster is not visible scan evidence")
            signals = {
                **source, "byte_size": len(raw), "page_count": pdf.page_count,
                "native_characters_by_page": characters,
                "largest_image_coverage_by_page": coverage,
                "inspection_grayscale_range_by_page": contrast,
                "pdf_creator": pdf.metadata.get("creator", ""),
                "pdf_producer": pdf.metadata.get("producer", ""),
            }
        attachment = StoredAttachment(source["sha256"], len(raw), "application/pdf",
                                      source["filename"], "offline-evaluation", raw)
        native = parse_document(attachment)
        quality = assess_text_quality(native)
        if quality.status != "needs_ocr":
            raise ValueError("scan must use the production needs_ocr route")
        signals["native_quality_status"] = quality.status
        inputs.append((signals, OcrDocument(attachment, native)))
    return inputs


async def evaluate_scans(
    manifest: dict[str, Any], directory: Path, config: RuntimeOcrConfig,
) -> dict[str, Any]:
    inputs = scan_inputs(manifest, directory, config)
    native_rows, rows = [], []
    adapter = None
    probe_error = None
    try:
        adapter = await TesseractOcrAdapter.create(config)
    except (RuntimeError, OSError, TimeoutError) as error:
        probe_error = type(error).__name__
    attempts = 0
    for source, document in inputs:
        expected = source["expected_fields"]
        page_number = source["page"]
        native_text = document.native_parse.pages[page_number - 1].text
        native_rows.append({
            "id": source["id"], "status": "measured", "scored_page": page_number,
            "text_sha256": hashlib.sha256(native_text.encode()).hexdigest(),
            "anchors": anchor_metrics(native_text, source["recognition_anchors"]),
            **await score_text(native_text, expected),
        })
        row: dict[str, Any] = {
            "id": source["id"], "status": "failed", "scored_page": page_number,
            "expected_field_count": len(expected), "elapsed_ms": None,
        }
        if adapter is None:
            row["reason"] = "probe_failed"
            row["error_type"] = probe_error
            rows.append(row)
            continue
        start = time.perf_counter()
        attempts += 1
        try:
            result = await adapter.recognize(document)
            row["elapsed_ms"] = (time.perf_counter() - start) * 1000
            if (result.status != "recognized" or result.synthetic is not False
                    or result.provider != "tesseract_pymupdf"
                    or len(result.pages) != document.native_parse.page_count
                    or [page.page_number for page in result.pages]
                    != list(range(1, document.native_parse.page_count + 1))
                    or result.text_sha256
                    != hashlib.sha256(result.extracted_text.encode()).hexdigest()
                    or result.extracted_text != "\n\n".join(page.text for page in result.pages)):
                raise RuntimeError("invalid recognition provenance")
            text = result.pages[page_number - 1].text
            row.update({
                "status": "measured", "provider": result.provider,
                "provider_version": result.provider_version, "synthetic": False,
                "recognized_pages": len(result.pages),
                "document_text_sha256": result.text_sha256,
                "scored_page_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "scored_page_characters": len(text),
                "anchors": anchor_metrics(text, source["recognition_anchors"]),
                **await score_text(text, expected),
            })
        except (RuntimeError, OSError, TimeoutError) as error:
            row.update(status="failed", reason="recognition_failed",
                       error_type=type(error).__name__,
                       elapsed_ms=(time.perf_counter() - start) * 1000)
        rows.append(row)
    aggregate = summary(rows)
    # Even incomplete measurements retain every annotated field in the denominator.
    aggregate["expected_fields"] = sum(len(source["expected_fields"]) for source, _ in inputs)
    aggregate["expected_anchors"] = sum(len(source["recognition_anchors"]) for source, _ in inputs)
    return {
        "sources": [source for source, _ in inputs],
        "image_only_documents": len(inputs),
        "original_pdf_pages": sum(document.native_parse.page_count for _, document in inputs),
        "annotated_pages": len(inputs),
        "runtime_identity": adapter.identity if adapter is not None else None,
        "real_pdf_recognition_attempts": attempts,
        "native_control": {"summary": summary(native_rows), "rows": native_rows},
        "runtime": {"summary": aggregate, "rows": rows},
    }
