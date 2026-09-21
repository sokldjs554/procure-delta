"""Static delivery contracts only; these do not pretend to be Docker integration."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class ReleaseDeliveryTests(unittest.TestCase):
    def test_readme_has_required_footer_and_no_license_claim(self) -> None:
        text = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertNotRegex(text, r'(?i)\bMIT\b')
        self.assertTrue(text.rstrip().endswith(
            'Copyright © 2026 윤기혁. All rights reserved. Portfolio project.'))
        self.assertFalse((ROOT / 'LICENSE').exists())

    def test_public_summary_is_exact_measured_artifact_not_handwritten_stats(self) -> None:
        source = (ROOT / 'artifacts/evaluation/local.json').read_bytes()
        published = (ROOT / 'apps/api/app/evaluation/results/local.json').read_bytes()
        self.assertEqual(source, published)
        result = json.loads(source)
        self.assertEqual(result['public_real_records'], 0)
        self.assertEqual(result['ocr']['actual_recognition_invocations'], 1)
        self.assertEqual(result['extraction_routes']['hosted_all']['status'], 'not_run')

    def test_cpu_artifact_does_not_claim_database_or_http_measurement(self) -> None:
        result = json.loads((ROOT / 'artifacts/performance/cpu.json').read_text())
        self.assertEqual(result['scope'], 'cpu_only_production_functions')
        self.assertEqual(result['normalized_records'], 50000)
        self.assertEqual(result['database_calls'], 0)
        self.assertIsNone(result['api_p95_ms'])
        self.assertIsNone(result['arq_records_per_second'])

    def test_default_compose_uses_loopback_ports_and_notification_config(self) -> None:
        text = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
        for port in (3000, 8000, 5432, 6379):
            self.assertIn(f'127.0.0.1:{port}:{port}', text)
        self.assertIn('NOTIFICATION_EXTERNAL_ENABLED', text)
        self.assertIn('NOTIFICATION_WEBHOOK_DESTINATIONS', text)
        env = (ROOT / '.env.example').read_text(encoding='utf-8')
        self.assertIn('NOTIFICATION_WEBHOOK_DESTINATIONS={}', env)

    def test_verification_stack_uses_private_ports_and_distinct_databases(self) -> None:
        text = (ROOT / 'compose.verify.yml').read_text()
        for port in (13000, 18000, 15432, 16379):
            self.assertIn(f'127.0.0.1:{port}:', text)
        self.assertIn('procure_delta_verify_test', text)
        self.assertIn('procure_delta_verify_bench', text)
        runner = (ROOT / 'scripts/verify_containers.py').read_text()
        self.assertIn("'--env-file', os.devnull", runner)
        self.assertNotIn("'procure-delta'", runner)


    def test_backend_gate_runs_isolation_regression_and_surfaces_subgates(self) -> None:
        checks = (ROOT / 'scripts/container_checks.py').read_text(encoding='utf-8')
        self.assertIn("'backend-db-isolation-regression'", checks)
        for test_path in (
            'tests/db/test_schema.py',
            'tests/demo/test_seed_integration.py',
            'tests/domain/test_versioning.py',
            'tests/ranking/test_eligibility.py',
            'tests/sources/test_koneps_mapping.py',
            'tests/test_database_isolation.py',
        ):
            self.assertIn(test_path, checks)
        runner = (ROOT / 'scripts/verify_containers.py').read_text(encoding='utf-8')
        self.assertIn("'checks.json'", runner)
        self.assertIn("'backend_subgates'", runner)

    def test_browser_gate_is_real_backend_not_response_mock(self) -> None:
        text = (ROOT / 'apps/web/e2e/lifecycle.mjs').read_text()
        self.assertNotIn('route.fulfill', text)
        self.assertNotIn('page.route(', text)
        for gate in ('"amendment"', '"outcome"', 'watched_material_change', 'receipt_id'):
            self.assertIn(gate, text)

    def test_product_browser_regression_is_part_of_release_gate(self) -> None:
        runner = (ROOT / 'scripts/verify_containers.py').read_text(encoding='utf-8')
        self.assertIn("'product-browser-regression'", runner)
        self.assertIn("'tests/product.browser.mjs'", runner)
        self.assertIn("'E2E_WEB_URL': 'http://127.0.0.1:13000'", runner)
        self.assertIn("'E2E_API_URL': 'http://127.0.0.1:18000'", runner)

    def test_pipeline_demo_is_part_of_release_gate_and_public_measurement_contract(self) -> None:
        runner = (ROOT / 'scripts/verify_containers.py').read_text(encoding='utf-8')
        self.assertIn("'pipeline-demo-e2e'", runner)
        for path in (
            'artifacts/performance/queue.json',
            'artifacts/performance/http.json',
            'artifacts/performance/query-plans.json',
        ):
            self.assertIn(path, runner)
        workflow = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertIn('artifacts/performance', workflow)

    def test_required_documentation_and_scripts_exist(self) -> None:
        for path in (
            'docs/architecture.md', 'docs/data-pipeline.md', 'docs/operations.md',
            'docs/limitations.md', 'docs/evaluation.md', 'docs/performance.md',
            'scripts/load_test.py', 'scripts/seed_demo.py', 'scripts/seed_scale.py',
            'scripts/query_plans.py', 'scripts/failure_drill.py', 'scripts/verify_containers.py',
        ):
            self.assertTrue((ROOT / path).is_file(), path)
