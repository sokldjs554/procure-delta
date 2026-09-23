"""DB-free validation and reference evidence contracts; no throughput claims."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api import performance
from app.evaluation.integration import backfill_load


class BackfillDeliveryTests(unittest.TestCase):
    def test_rejects_first_batch_exceeding_production_page_budget(self) -> None:
        # Invalid combinations must fail before inspecting or opening a database.
        with (
            patch.dict(os.environ, {"BENCH_DATABASE_URL": "sqlite:///not-allowed.db"}),
            self.assertRaisesRegex(ValueError, "first_batch_pages.*100"),
        ):
            asyncio.run(backfill_load(200, page_size=1, first_batch_pages=101))

    def test_rejects_resume_exceeding_production_page_budget(self) -> None:
        with (
            patch.dict(os.environ, {"BENCH_DATABASE_URL": "sqlite:///not-allowed.db"}),
            self.assertRaisesRegex(ValueError, "remaining pages.*100"),
        ):
            asyncio.run(backfill_load(2000, page_size=10, first_batch_pages=5))

    def test_checkout_and_packaged_release_evidence_match(self) -> None:
        checkout = performance.engineering_evidence()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(performance, "ARTIFACT_ROOT", Path(directory)),
        ):
            packaged = performance.engineering_evidence()
        # The two historical runs have distinct timing values, but the same gates.
        self.assertEqual(
            [(gate.gate, gate.passed) for gate in packaged.release.gates],
            [(gate.gate, gate.passed) for gate in checkout.release.gates],
        )
        self.assertEqual(packaged.backfill.metrics["records"], 2000)
        self.assertTrue(packaged.backfill.metrics["resumed_from_checkpoint"])
