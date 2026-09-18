"""Delivery contracts independent of PostgreSQL/Redis. Not integration tests."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class DeliveryTests(unittest.TestCase):
    def test_compose_forwards_source_config_to_api_worker_scheduler(self) -> None:
        text = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
        for service in ('api', 'worker', 'scheduler'):
            block = re.search(r'^  '+service+r':\n(.*?)(?=^  \w+:|\Z)', text, re.M | re.S)
            self.assertIsNotNone(block)
            assert block is not None
            for field in ('KONEPS_ENABLED', 'KONEPS_SERVICE_KEY', 'KONEPS_LOOKBACK_DAYS'):
                with self.subTest(service=service, field=field):
                    self.assertIn(field+': ${'+field, block.group(1))

    def test_environment_example_is_opt_in_and_contains_no_key(self) -> None:
        text = (ROOT / '.env.example').read_text(encoding='utf-8')
        self.assertIn('KONEPS_ENABLED=false', text)
        self.assertRegex(text, r'(?m)^KONEPS_SERVICE_KEY=$')
        self.assertIn('KONEPS_LOOKBACK_DAYS=1', text)

    def test_contract_document_has_honest_coverage_and_commands(self) -> None:
        path = ROOT / 'docs/source-contracts.md'
        self.assertTrue(path.exists(), 'missing source contract documentation')
        text = path.read_text(encoding='utf-8')
        for expected in ('15129394', 'getBidPblancListInfoServc', '--live', '--fixture',
                         'presmptPrce', '사전규격', '낙찰', '계약', '미검증'):
            self.assertIn(expected, text)

    def test_fixture_smoke_is_explicitly_synthetic(self) -> None:
        module = importlib.util.find_spec('app.sources.koneps_smoke')
        self.assertIsNotNone(module, 'smoke module missing')
        result = subprocess.run([sys.executable, '-m', 'app.sources.koneps_smoke', '--fixture'],
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary['mode'], 'synthetic_contract')
        self.assertFalse(summary['live_verified'])
        self.assertEqual(summary['records_checked'], 1)
        self.assertFalse(summary['database_written'])

    def test_live_smoke_without_key_fails_without_network_or_secret(self) -> None:
        module = importlib.util.find_spec('app.sources.koneps_smoke')
        self.assertIsNotNone(module, 'smoke module missing')
        environment = {**os.environ, 'KONEPS_SERVICE_KEY': ''}
        result = subprocess.run([sys.executable, '-m', 'app.sources.koneps_smoke', '--live'],
                                text=True, capture_output=True, env=environment, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn('KONEPS_SERVICE_KEY', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_unittest_contracts_are_in_ci(self) -> None:
        text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertIn('python -m unittest discover -s contract_tests', text)

    def test_custom_loop_hook_has_correct_minimum_dependency(self) -> None:
        text = (ROOT / 'apps/api/pyproject.toml').read_text(encoding='utf-8')
        self.assertIn('pytest-asyncio>=1.4', text)
