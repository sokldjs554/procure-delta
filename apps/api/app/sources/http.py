from __future__ import annotations

import asyncio
import logging
import math
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)
MAX_AUTOMATIC_RETRY_AFTER_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class RetryAfterPolicy:
    """Safe scheduling facts only; never retain a raw header, URL, or response body."""

    retry_not_before: datetime | None
    requires_review: bool = False


class RetryAfterDeadlineExceeded(TimeoutError):
    def __init__(self, retry_policy: RetryAfterPolicy) -> None:
        self.retry_policy = retry_policy
        super().__init__("Upstream retry requires scheduling outside the request deadline")


class RetryableHTTPStatusError(httpx.HTTPStatusError):
    def __init__(self, response: httpx.Response, retry_policy: RetryAfterPolicy | None) -> None:
        self.retry_policy = retry_policy
        super().__init__(
            f"Retryable upstream response: {response.status_code}",
            request=response.request, response=response,
        )


def retry_policy_for_error(error: Exception) -> RetryAfterPolicy | None:
    if isinstance(error, (RetryAfterDeadlineExceeded, RetryableHTTPStatusError)):
        return error.retry_policy
    return None


@dataclass
class _RetryState:
    policy: RetryAfterPolicy | None = None


def _retry_after_delay(value: str | None, *, observed_at: float) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value):
        # An enormous valid delay becomes infinity and cannot fit the deadline.
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            # The obsolete asctime HTTP-date format still means UTC.
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, retry_at.timestamp() - observed_at)
    except (ValueError, TypeError, OverflowError):
        return None


def _retry_after_policy(value: str | None) -> RetryAfterPolicy | None:
    observed_at = time.time()
    delay = _retry_after_delay(value, observed_at=observed_at)
    if delay is None:
        return None
    if not math.isfinite(delay) or delay > MAX_AUTOMATIC_RETRY_AFTER_SECONDS:
        return RetryAfterPolicy(retry_not_before=None, requires_review=True)
    return RetryAfterPolicy(retry_not_before=datetime.fromtimestamp(observed_at + delay, tz=UTC))


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
        )

    async def __aenter__(self) -> ResilientHttpClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send one request, retrying only retryable upstream failures."""
        deadline = asyncio.get_running_loop().time() + self.total_timeout_seconds
        state = _RetryState()
        try:
            async with asyncio.timeout_at(deadline):
                return await self._request_with_retries(
                    method, url, deadline=deadline, state=state, **kwargs
                )
        except TimeoutError as error:
            if state.policy is not None and not isinstance(error, RetryAfterDeadlineExceeded):
                # An overall timeout while waiting must not lose the outer worker's cooldown.
                raise RetryAfterDeadlineExceeded(state.policy) from None
            raise

    async def _request_with_retries(
        self, method: str, url: str, *, deadline: float, state: _RetryState, **kwargs: Any
    ) -> httpx.Response:
        for attempt in range(1, self.max_attempts + 1):
            started = time.perf_counter()
            try:
                response = await self._client.request(method, url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    state.policy = _retry_after_policy(response.headers.get("retry-after"))
                    error = RetryableHTTPStatusError(response, state.policy)
                    self._log_attempt(response, attempt, started, "retryable_error")
                    if attempt == self.max_attempts:
                        raise error
                    await self._sleep_before_retry(
                        attempt, deadline=deadline,
                        retry_policy=state.policy,
                    )
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
                await self._sleep_before_retry(attempt, deadline=deadline)

        raise RuntimeError("retry loop exhausted unexpectedly")

    async def _sleep_before_retry(
        self, attempt: int, *, deadline: float, retry_policy: RetryAfterPolicy | None = None
    ) -> None:
        delay = self.backoff_base_seconds * (2 ** (attempt - 1))
        delay += self._jitter(delay)
        if retry_policy is not None:
            if retry_policy.requires_review:
                raise RetryAfterDeadlineExceeded(retry_policy)
            if retry_policy.retry_not_before is not None:
                delay = max(delay, retry_policy.retry_not_before.timestamp() - time.time())
        if delay >= deadline - asyncio.get_running_loop().time():
            if retry_policy is not None:
                raise RetryAfterDeadlineExceeded(retry_policy)
            raise TimeoutError("Upstream retry delay exceeds the request deadline")
        await self._sleeper(delay)

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
