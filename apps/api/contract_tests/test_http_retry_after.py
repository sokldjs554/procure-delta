"""Offline retry timing contracts; every HTTP response uses a controlled transport."""
from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx

from app.sources.http import ResilientHttpClient
from app.workers import jobs

UTC_2030 = 1893456000.0


class RetryAfterTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(
        self,
        value: str,
        *,
        status: int = 429,
        total_timeout_seconds: float = 10,
        max_attempts: int = 3,
        backoff_base_seconds: float = 0.25,
    ) -> tuple[httpx.Response | Exception, int, list[float]]:
        attempts = 0
        sleeps: list[float] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(status, headers={"Retry-After": value}, request=request)
            return httpx.Response(200, json={"ok": True}, request=request)

        async def record_sleep(delay: float) -> None:
            sleeps.append(delay)

        with patch("app.sources.http.time.time", return_value=UTC_2030):
            async with ResilientHttpClient(
                transport=httpx.MockTransport(handler),
                total_timeout_seconds=total_timeout_seconds,
                max_attempts=max_attempts,
                backoff_base_seconds=backoff_base_seconds,
                sleeper=record_sleep,
                jitter=lambda _: 0,
            ) as client:
                try:
                    outcome: httpx.Response | Exception = await client.request(
                        "GET", "https://source.example/records"
                    )
                except Exception as error:
                    outcome = error
        return outcome, attempts, sleeps

    async def test_retryable_status_waits_at_least_the_server_delay(self) -> None:
        for status in (429, 500, 503):
            with self.subTest(status=status):
                outcome, attempts, sleeps = await self.exercise(" 2 ", status=status)
                self.assertIsInstance(outcome, httpx.Response)
                self.assertEqual(attempts, 2)
                self.assertEqual(sleeps, [2.0])

    async def test_http_date_forms_use_utc_wall_clock(self) -> None:
        for value in (
            "Tue, 01 Jan 2030 00:00:05 GMT",
            "Tuesday, 01-Jan-30 00:00:05 GMT",
            "Tue Jan  1 00:00:05 2030",
        ):
            with self.subTest(value=value):
                outcome, attempts, sleeps = await self.exercise(value)
                self.assertIsInstance(outcome, httpx.Response)
                self.assertEqual(attempts, 2)
                self.assertEqual(sleeps, [5.0])

    async def test_zero_or_past_date_keeps_the_existing_backoff(self) -> None:
        for value in ("0", "Mon, 31 Dec 2029 23:59:59 GMT"):
            with self.subTest(value=value):
                outcome, attempts, sleeps = await self.exercise(value)
                self.assertIsInstance(outcome, httpx.Response)
                self.assertEqual(attempts, 2)
                self.assertEqual(sleeps, [0.25])

    async def test_server_delay_does_not_shorten_the_local_backoff(self) -> None:
        outcome, attempts, sleeps = await self.exercise("2", backoff_base_seconds=4)
        self.assertIsInstance(outcome, httpx.Response)
        self.assertEqual(attempts, 2)
        self.assertEqual(sleeps, [4.0])

    async def test_malformed_values_keep_bounded_exponential_backoff(self) -> None:
        for value in ("", "invalid", "-1", "+2", "1.5", "1e2", "nan", "inf", "1, 2"):
            with self.subTest(value=value):
                outcome, attempts, sleeps = await self.exercise(value)
                self.assertIsInstance(outcome, httpx.Response)
                self.assertEqual(attempts, 2)
                self.assertEqual(sleeps, [0.25])

    async def test_delay_that_cannot_fit_deadline_never_retries_early(self) -> None:
        for value in ("60", "9" * 400, "Tue, 01 Jan 2030 00:01:00 GMT"):
            with self.subTest(value=value[:40]):
                outcome, attempts, sleeps = await self.exercise(value, total_timeout_seconds=0.02)
                self.assertIsInstance(outcome, TimeoutError)
                self.assertEqual(attempts, 1)
                self.assertEqual(sleeps, [])

    async def test_header_does_not_retry_a_terminal_status_or_exhausted_attempt(self) -> None:
        for status, max_attempts in ((403, 3), (429, 1)):
            with self.subTest(status=status, max_attempts=max_attempts):
                outcome, attempts, sleeps = await self.exercise(
                    "60", status=status, max_attempts=max_attempts, total_timeout_seconds=0.02
                )
                self.assertIsInstance(outcome, httpx.HTTPStatusError)
                self.assertEqual(attempts, 1)
                self.assertEqual(sleeps, [])

    async def test_deadline_failure_preserves_the_server_retry_instant_for_the_worker(self) -> None:
        for value in ("60", "Tue, 01 Jan 2030 00:01:00 GMT"):
            with self.subTest(value=value):
                outcome, attempts, sleeps = await self.exercise(value, total_timeout_seconds=0.02)
                self.assertIsInstance(outcome, TimeoutError)
                policy = getattr(outcome, "retry_policy", None)
                self.assertIsNotNone(policy, "The outer job needs the server cooldown")
                self.assertEqual(
                    policy.retry_not_before,
                    datetime.fromtimestamp(UTC_2030 + 60, tz=UTC),
                )
                self.assertFalse(policy.requires_review)
                self.assertEqual((attempts, sleeps), (1, []))

    async def test_final_http_failure_keeps_the_same_retry_policy(self) -> None:
        outcome, attempts, sleeps = await self.exercise("60", max_attempts=1)
        self.assertIsInstance(outcome, httpx.HTTPStatusError)
        policy = getattr(outcome, "retry_policy", None)
        self.assertIsNotNone(policy, "Exhausted HTTP attempts must retain Retry-After")
        self.assertEqual(
            policy.retry_not_before, datetime.fromtimestamp(UTC_2030 + 60, tz=UTC)
        )
        self.assertFalse(policy.requires_review)
        self.assertEqual((attempts, sleeps), (1, []))

    async def test_excessive_delays_need_review_instead_of_an_early_automatic_retry(self) -> None:
        for value in ("86401", "9" * 400, "Thu, 03 Jan 2030 00:00:00 GMT"):
            for max_attempts in (1, 3):
                with self.subTest(value=value[:40], max_attempts=max_attempts):
                    outcome, attempts, sleeps = await self.exercise(
                        value, total_timeout_seconds=0.02, max_attempts=max_attempts
                    )
                    self.assertIsInstance(outcome, Exception)
                    assert isinstance(outcome, Exception)
                    policy = getattr(outcome, "retry_policy", None)
                    self.assertIsNotNone(policy, "Unbounded hints need an explicit safe policy")
                    self.assertTrue(policy.requires_review)
                    self.assertIsNone(policy.retry_not_before)
                    self.assertFalse(jobs._is_transient(outcome))
                    self.assertEqual((attempts, sleeps), (1, []))

    async def test_poll_retry_clock_uses_the_later_server_instant_or_local_backoff(self) -> None:
        retry_at = getattr(jobs, "_poll_retry_not_before", None)
        self.assertTrue(callable(retry_at), "Polling must share one durable retry clock")
        outcome, _, _ = await self.exercise("60", total_timeout_seconds=0.02)
        assert isinstance(outcome, Exception)
        now = datetime.fromtimestamp(UTC_2030 + 10, tz=UTC)
        self.assertEqual(retry_at(outcome, attempts=1, now=now), now + timedelta(seconds=50))
        self.assertEqual(
            retry_at(outcome, attempts=2, now=now + timedelta(seconds=59)),
            now + timedelta(seconds=63),
        )
        self.assertIsNone(retry_at(outcome, attempts=jobs.MAX_ATTEMPTS, now=now))
        self.assertIsNone(retry_at(ValueError("terminal"), attempts=1, now=now))

    async def test_cancellation_while_waiting_stops_further_attempts(self) -> None:
        sleeping = asyncio.Event()
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(429, headers={"Retry-After": "1"}, request=request)

        async def blocked_sleep(_delay: float) -> None:
            sleeping.set()
            await asyncio.Event().wait()

        async with ResilientHttpClient(
            transport=httpx.MockTransport(handler), sleeper=blocked_sleep, jitter=lambda _: 0
        ) as client:
            task = asyncio.create_task(client.request("GET", "https://source.example/records"))
            await asyncio.wait_for(sleeping.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(attempts, 1)


if __name__ == "__main__":
    unittest.main()
