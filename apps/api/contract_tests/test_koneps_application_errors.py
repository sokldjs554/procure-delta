"""Synthetic HTTP-200 error envelopes; no public API or service key is used."""
from __future__ import annotations

import unittest

import httpx

from app.sources.http import ResilientHttpClient
from app.sources.koneps import KonepsSourceAdapter
from app.workers.jobs import _is_transient


class KonepsApplicationErrorTests(unittest.IsolatedAsyncioTestCase):
    async def application_failure(self, code: object) -> Exception:
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(
                200,
                request=request,
                json={
                    "response": {
                        "header": {
                            "resultCode": code,
                            "resultMsg": "synthetic-private-message serviceKey=synthetic-only-key",
                        }
                    }
                },
            )

        async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as client:
            adapter = KonepsSourceAdapter(service_key="synthetic-only-key", client=client)
            try:
                await adapter.discover(None)
            except ValueError as error:
                self.assertEqual(attempts, 1)  # ARQ owns the existing durable retry budget.
                self.assertNotIn("synthetic-private-message", str(error))
                self.assertNotIn("synthetic-only-key", str(error))
                return error
        self.fail("Application error envelope must not become a successful discovery page")

    async def test_documented_transient_codes_use_the_worker_retry_policy(self) -> None:
        for code in ("01", "05", "23"):
            with self.subTest(code=code):
                error = await self.application_failure(code)
                self.assertTrue(_is_transient(error))
                self.assertEqual(type(error).__name__, "KonepsTransientApplicationError")
                self.assertEqual(getattr(error, "code", None), code)

    async def test_configuration_daily_quota_and_unknown_codes_stay_terminal(self) -> None:
        for code in ("04", "10", "12", "20", "22", "29", "30", "31", "99"):
            with self.subTest(code=code):
                error = await self.application_failure(code)
                self.assertFalse(_is_transient(error))
                self.assertEqual(type(error).__name__, "KonepsApplicationError")
                self.assertEqual(getattr(error, "code", None), code)

    async def test_untrusted_application_code_cannot_become_exception_text(self) -> None:
        for code in ("synthetic-private-message", None, False, {"secret": "synthetic-only-key"}):
            with self.subTest(kind=type(code).__name__):
                error = await self.application_failure(code)
                self.assertFalse(_is_transient(error))
                self.assertEqual(getattr(error, "code", None), "unknown")


if __name__ == "__main__":
    unittest.main()
