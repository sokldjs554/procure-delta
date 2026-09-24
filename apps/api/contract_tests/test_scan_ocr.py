"""Offline evidence must use original image-only PDFs and retain failed cases."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from PIL import Image, ImageDraw

from app.documents.ocr import OcrResult
from app.documents.ocr_runtime import RuntimeOcrConfig
from app.documents.parsers import ParsedPage
from app.evaluation.scan_documents import evaluate_scans


def pdf_bytes(*, native=False, blank=False, width=300, uniform=False, vector=False):
    image = io.BytesIO()
    raster = Image.new("L", (300, 300), 240)
    if not uniform:
        ImageDraw.Draw(raster).text((20, 30), "Visible raster text", fill=0)
    raster.save(image, format="PNG")
    with pymupdf.open() as pdf:
        for _ in range(2):
            page = pdf.new_page(width=width, height=300)
            if not blank:
                page.insert_image(page.rect, stream=image.getvalue())
        if native:
            pdf[1].insert_text((20, 30), "Hidden native text on the unscored page")
        if vector:
            pdf[1].draw_rect((20, 20, 200, 200), color=(0, 0, 0))
        return pdf.tobytes()


def source(directory, raw, name="first", page=1):
    (directory / f"{name}.pdf").write_bytes(raw)
    return {
        "id": name, "filename": f"{name}.pdf", "page": page,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "expected_fields": {"title": "Project", "buyer_name": "Agency",
                            "procurement_type": "services"},
        "recognition_anchors": {"title": "Project", "buyer": "Agency"},
    }


def manifest(sources):
    return {"source_kind": "image_only_public_pdf", "sources": sources}


def recognized(text, *, synthetic=False):
    pages = (ParsedPage(1, "Title: Wrong page"), ParsedPage(2, text))
    combined = "\n\n".join(page.text for page in pages)
    return OcrResult("tesseract_pymupdf", "test-runtime", synthetic, pages, combined,
                     hashlib.sha256(combined.encode()).hexdigest(), "recognized")


class ScanOcrTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_pdf_is_recognized_and_only_annotated_page_is_scored(self):
        raw = pdf_bytes()
        inputs = []
        text = "Title: Project\nBuyer: Agency\nCategory: services\nPrivate unscored material"

        async def recognize(adapter, document):
            inputs.append(document)
            return recognized(text)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch("app.evaluation.scan_documents.TesseractOcrAdapter.create") as create:
                from app.documents.ocr_runtime import TesseractOcrAdapter
                create.return_value = TesseractOcrAdapter(RuntimeOcrConfig(), "0" * 64)
                with patch.object(TesseractOcrAdapter, "recognize", recognize):
                    result = await evaluate_scans(
                        manifest([source(directory, raw, page=2)]), directory, RuntimeOcrConfig(),
                    )
        self.assertEqual(inputs[0].attachment.original_bytes, raw)
        self.assertIsNone(inputs[0].fixture_key)
        self.assertEqual(result["runtime"]["summary"]["trusted_correct_fields"], 3)
        self.assertEqual(result["runtime"]["summary"]["expected_fields"], 3)
        self.assertEqual(result["native_control"]["summary"]["trusted_correct_fields"], 0)
        self.assertEqual(result["sources"][0]["native_characters_by_page"], [0, 0])
        self.assertEqual(result["runtime"]["rows"][0]["scored_page"], 2)
        self.assertIsNone(result["runtime"]["rows"][0]["rejection_stage"])
        native_row = result["native_control"]["rows"][0]
        self.assertEqual(native_row["rejection_stage"], "schema")
        self.assertEqual(native_row["schema_error_fields"],
                         ["buyer_name", "procurement_type", "title"])
        self.assertEqual(native_row["grounding_issues"], [])
        self.assertNotIn("Private unscored material", json.dumps(result))
        self.assertNotIn("Title: Wrong page", json.dumps(result))

    async def test_all_sources_are_validated_before_any_ocr(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first = source(directory, pdf_bytes())
            second = source(directory, pdf_bytes(), "second")
            (directory / "second.pdf").write_bytes(b"changed")
            with patch("app.evaluation.scan_documents.TesseractOcrAdapter.create") as create:
                with self.assertRaisesRegex(ValueError, "checksum"):
                    await evaluate_scans(manifest([first, second]), directory, RuntimeOcrConfig())
                create.assert_not_called()

    async def test_native_blank_oversize_and_wrong_page_are_not_scan_evidence(self):
        for kwargs, page in (({"native": True}, 1), ({"blank": True}, 1),
                             ({"width": 10000}, 1), ({}, 3), ({}, True)):
            with self.subTest(kwargs=kwargs, page=page), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                item = source(directory, pdf_bytes(**kwargs), page=page)
                with patch("app.evaluation.scan_documents.TesseractOcrAdapter.create") as create:
                    with self.assertRaises(ValueError):
                        await evaluate_scans(manifest([item]), directory, RuntimeOcrConfig())
                    create.assert_not_called()

    async def test_uniform_raster_and_vector_overlay_are_rejected(self):
        for kwargs in ({"uniform": True}, {"vector": True}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                item = source(directory, pdf_bytes(**kwargs))
                with patch("app.evaluation.scan_documents.TesseractOcrAdapter.create") as create:
                    with self.assertRaises(ValueError):
                        await evaluate_scans(manifest([item]), directory, RuntimeOcrConfig())
                    create.assert_not_called()

    async def test_failure_keeps_denominator_and_prevents_partial_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            sources = [source(directory, pdf_bytes(), name, page=2) for name in ("a", "b")]
            from app.documents.ocr_runtime import TesseractOcrAdapter
            with (
                patch.object(TesseractOcrAdapter, "create") as create,
                patch.object(TesseractOcrAdapter, "recognize", side_effect=[
                    recognized("Title: Project\nBuyer: Agency\nCategory: services"),
                    TimeoutError("sensitive detail must not be published"),
                ]),
            ):
                create.return_value = TesseractOcrAdapter(RuntimeOcrConfig(), "0" * 64)
                result = await evaluate_scans(manifest(sources), directory, RuntimeOcrConfig())
        aggregate = result["runtime"]["summary"]
        self.assertEqual(aggregate["status"], "incomplete")
        self.assertEqual(aggregate["cases"], 2)
        self.assertEqual(aggregate["expected_fields"], 6)
        self.assertEqual(aggregate["expected_anchors"], 4)
        self.assertIsNone(aggregate["trusted_field_accuracy"])
        self.assertNotIn("sensitive detail", json.dumps(result))

    async def test_fixture_output_cannot_be_published_as_real_ocr(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            from app.documents.ocr_runtime import TesseractOcrAdapter
            with (
                patch.object(TesseractOcrAdapter, "create") as create,
                patch.object(TesseractOcrAdapter, "recognize", return_value=recognized(
                    "Title: Project\nBuyer: Agency\nCategory: services", synthetic=True,
                )),
            ):
                create.return_value = TesseractOcrAdapter(RuntimeOcrConfig(), "0" * 64)
                result = await evaluate_scans(
                    manifest([source(directory, pdf_bytes(), page=2)]), directory,
                    RuntimeOcrConfig(),
                )
        self.assertEqual(result["runtime"]["summary"]["status"], "incomplete")
        self.assertIsNone(result["runtime"]["summary"]["trusted_field_accuracy"])


if __name__ == "__main__":
    unittest.main()
