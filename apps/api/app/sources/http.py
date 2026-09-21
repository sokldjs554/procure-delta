from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class _SecretQueryFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = re.sub(r"(?i)(servicekey=)[^&\s\"']+", r"\1[redacted]", record.getMessage())
        record.args = ()
        return True


class ResilientHttpClient:
    """Async HTTP client with an overall request deadline and bounded retries."""

    def __init__(
        self,
        *,
        connect_timeout_seconds: float = 5.0,
        total_timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        backoff_base_seconds: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        if connect_timeout_seconds <= 0 or total_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if backoff_base_seconds < 0:
            raise ValueError("backoff_base_seconds cannot be negative")

        self.connect_timeout_seconds = connect_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds
        self._sleeper = sleeper
        self._jitter = jitter or (lambda delay: random.uniform(0, delay * 0.1))
        http_logger = logging.getLogger("httpx")
        if not any(isinstance(item, _SecretQueryFilter) for item in http_logger.filters):
            http_logger.addFilter(_SecretQueryFilter())
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(total_timeout_seconds, connect=connect_timeout_seconds),
            trust_env=False,
        )

    async def __aenter__(self) -> ResilientHttpClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send one request, retrying only retryable upstream failures."""
        async with asyncio.timeout(self.total_timeout_seconds):
            return await self._request_with_retries(method, url, **kwargs)

    async def _request_with_retries(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        for attempt in range(1, self.max_attempts + 1):
            started = time.perf_counter()
            try:
                response = await self._client.request(method, url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    error = httpx.HTTPStatusError(
                        f"Retryable upstream response: {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    self._log_attempt(response, attempt, started, "retryable_error")
                    if attempt == self.max_attempts:
                        raise error
                    await self._sleep_before_retry(attempt)
                    continue

                if response.is_error:
                    self._log_attempt(response, attempt, started, "non_retryable_error")
                    raise httpx.HTTPStatusError(
                        f"Non-retryable upstream response: {response.status_code}",
                        request=response.request, response=response,
                    )

                self._log_attempt(response, attempt, started, "success")
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                self._log_exception(error, attempt, started)
                if attempt == self.max_attempts:
                    raise
                await self._sleep_before_retry(attempt)

        raise RuntimeError("retry loop exhausted unexpectedly")

    async def _sleep_before_retry(self, attempt: int) -> None:
        delay = self.backoff_base_seconds * (2 ** (attempt - 1))
        await self._sleeper(delay + self._jitter(delay))

    @staticmethod
    def _log_attempt(
        response: httpx.Response, attempt: int, started: float, result: str) -> None:
        logger.info(
            "source_http_request",
            extra={
                "request_id": response.headers.get("x-request-id"),
                "status": response.status_code,
                "attempt": attempt,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "result": result,
            },
        )

    @staticmethod
    def _log_exception(error: httpx.HTTPError, attempt: int, started: float) -> None:
        response = getattr(error, "response", None)
        logger.info(
            "source_http_request",
            extra={
                "request_id": response.headers.get("x-request-id") if response else None,
                "status": response.status_code if response else None,
                "attempt": attempt,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "result": "retryable_error",
            },
        )
