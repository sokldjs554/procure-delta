"""DB-free contracts for OCR provenance, trusted scores and process cleanup."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from app.evaluation import ocr
from app.evaluation.public_documents import (
    anchor_metrics,
    evaluate_public_documents,
    summary,
    verified_sources,
)


class PublicOcrTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_suite_keeps_all_variants_and_does_not_publish_full_text(self) -> None:
        private_text = "Full text must stay out of the published artifact. " * 3
        with pymupdf.open() as document:
            page = document.new_page(width=300, height=300)
            page.insert_textbox(page.rect, private_text)
            raw = document.tobytes()
        source = {
            "id": "example", "filename": "source.pdf", "page": 1,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "expected_fields": {"title": "Example"},
            "recognition_anchors": {"title": "Example"},
        }
        configurations = []

        async def fake_ocr(directory, *, page_segmentation_mode):
            case = json.loads((directory / "ocr_manifest.json").read_text())["cases"][0]
            configurations.append((case["synthetic"], page_segmentation_mode))
            return {
                "status": "measured", "rows": [{
                    "id": case["id"], "recognition_text": private_text,
                    **await ocr.score_text(private_text, source["expected_fields"]),
                }],
            }

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("app.evaluation.public_documents.evaluate_ocr", side_effect=fake_ocr),
        ):
            directory = Path(temporary)
            (directory / "source.pdf").write_bytes(raw)
            result = await evaluate_public_documents({"sources": [source]}, directory)
        self.assertEqual(configurations, [(False, 3)] * 3)
        self.assertEqual(result["ocr"]["summary"]["cases"], 3)
        self.assertTrue(all(value["cases"] == 1 for value in result["by_variant"].values()))
        self.assertNotIn("Full text must stay", json.dumps(result))
        self.assertEqual(result["native_control"]["summary"]["cases"], 1)
        self.assertEqual(result["ocr"]["summary"]["trusted_correct_fields"], 0)

    def test_anchors_ignore_spacing_but_preserve_wrong_amounts(self) -> None:
        measured = anchor_metrics("예산 40,000,000원", {"amount": "40,000,000 원"})
        self.assertEqual(measured["correct"], 1)
        self.assertEqual(anchor_metrics("400,000,000원", {"amount": "40,000,000원"})[
            "correct"
        ], 0)
        self.assertEqual(anchor_metrics("140,000,000원", {"amount": "40,000,000원"})[
            "correct"
        ], 0)
        with self.assertRaises(ValueError):
            anchor_metrics("anything", {"amount": " "})

    def test_incomplete_batch_cannot_publish_a_partial_success_score(self) -> None:
        measured = summary([{"status": "measured"}, {"status": "not_run"}])
        self.assertEqual(measured["status"], "incomplete")
        self.assertIsNone(measured["recognition_anchor_recall"])
        self.assertIsNone(measured["trusted_field_accuracy"])

    def test_tampered_and_escaping_pdf_sources_fail_before_recognition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            data = b"%PDF-1.7 fake"
            (directory / "source.pdf").write_bytes(data)
            source = {
                "id": "example", "filename": "source.pdf",
                "sha256": hashlib.sha256(data).hexdigest(),
                "expected_fields": {"title": "Example"},
                "recognition_anchors": {"title": "Example"},
            }
            self.assertEqual(verified_sources({"sources": [source]}, directory)[0][1], data)
            (directory / "source.pdf").write_bytes(data + b"changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                verified_sources({"sources": [source]}, directory)
            source["filename"] = "../source.pdf"
            with self.assertRaisesRegex(ValueError, "escapes"):
                verified_sources({"sources": [source]}, directory)

    def test_provenance_requires_explicit_uniform_boolean(self) -> None:
        self.assertTrue(ocr.synthetic_batch([{"synthetic": True}]))
        self.assertFalse(ocr.synthetic_batch([{"synthetic": False}]))
        for cases in (
            [{}], [{"synthetic": "false"}],
            [{"synthetic": True}, {"synthetic": False}],
        ):
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                ocr.synthetic_batch(cases)

    async def test_correct_partial_proposal_is_not_a_trusted_extraction(self) -> None:
        row = await ocr.score_text("Title: Example project", {"title": "Example project"})
        self.assertEqual(row["field_metrics"]["correct"], 1)
        self.assertFalse(row["downstream_valid"])
        self.assertEqual(row["trusted_field_metrics"]["correct"], 0)
        self.assertEqual(row["trusted_field_metrics"]["expected_fields"], 1)

    async def test_accepted_labeled_document_earns_trusted_credit(self) -> None:
        row = await ocr.score_text(
            "Title: Example project\nBuyer: Example agency\nCategory: services",
            {"title": "Example project", "buyer_name": "Example agency"},
        )
        self.assertTrue(row["downstream_valid"])
        self.assertEqual(row["trusted_field_metrics"]["correct"], 2)
        self.assertEqual(row["trusted_field_metrics"]["accuracy"], 1.0)

    async def test_timeout_and_cancellation_reap_real_child(self) -> None:
        create = asyncio.create_subprocess_exec
        children = []

        async def capture(*args, **kwargs):
            child = await create(*args, **kwargs)
            children.append(child)
            return child

        with patch.object(ocr.asyncio, "create_subprocess_exec", side_effect=capture):
            with self.assertRaises(TimeoutError):
                await ocr.run_command(sys.executable, "-c", "import time; time.sleep(10)",
                                      timeout=0.05)
            self.assertIsNotNone(children[-1].returncode)
            task = asyncio.create_task(ocr.run_command(
                sys.executable, "-c", "import time; time.sleep(10)", timeout=10,
            ))
            while len(children) < 2:
                await asyncio.sleep(0.005)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertIsNotNone(children[-1].returncode)


if __name__ == "__main__":
    unittest.main()
