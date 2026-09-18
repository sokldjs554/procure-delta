import asyncio

import httpx
import pytest

from app.sources.http import ResilientHttpClient


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 500, 503])
async def test_retries_retryable_statuses_within_max_attempts(status_code: int) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(
                status_code, request=request, headers={"x-request-id": "upstream-1"}
            )
        return httpx.Response(200, request=request, json={"ok": True})

    async with ResilientHttpClient(
        transport=httpx.MockTransport(handler), max_attempts=3, backoff_base_seconds=0
    ) as client:
        response = await client.request("GET", "https://source.example/records")

    assert response.status_code == 200
    assert attempts == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403])
async def test_does_not_retry_non_retryable_client_errors(status_code: int) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, request=request)

    async with ResilientHttpClient(
        transport=httpx.MockTransport(handler), max_attempts=3, backoff_base_seconds=0
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.request("GET", "https://source.example/records")

    assert attempts == 1


@pytest.mark.asyncio
async def test_retries_network_errors_within_max_attempts() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("unavailable", request=request)

    async with ResilientHttpClient(
        transport=httpx.MockTransport(handler), max_attempts=2, backoff_base_seconds=0
    ) as client:
        with pytest.raises(httpx.ConnectError):
            await client.request("GET", "https://source.example/records")

    assert attempts == 2


@pytest.mark.asyncio
async def test_raises_after_bounded_retryable_status_attempts() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, request=request)

    async with ResilientHttpClient(
        transport=httpx.MockTransport(handler), max_attempts=2, backoff_base_seconds=0
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await client.request("GET", "https://source.example/records")

    assert caught.value.response.status_code == 503
    assert attempts == 2


@pytest.mark.asyncio
async def test_configures_connect_and_total_timeouts_and_enforces_total_bound() -> None:
    observed_connect_timeout: float | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_connect_timeout
        observed_connect_timeout = request.extensions["timeout"]["connect"]
        await asyncio.sleep(0.1)
        return httpx.Response(200, request=request)

    async with ResilientHttpClient(
        transport=httpx.MockTransport(handler),
        connect_timeout_seconds=0.01,
        total_timeout_seconds=0.02,
        max_attempts=1,
    ) as client:
        assert client.connect_timeout_seconds == 0.01
        assert client.total_timeout_seconds == 0.02
        with pytest.raises(TimeoutError):
            await client.request("GET", "https://source.example/slow")

    assert observed_connect_timeout == 0.01


@pytest.mark.asyncio
async def test_retry_backoff_uses_exponential_delay_and_injected_jitter() -> None:
    delays: list[float] = []
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, request=request)

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async with ResilientHttpClient(
        transport=httpx.MockTransport(handler),
        max_attempts=3,
        backoff_base_seconds=1,
        sleeper=sleeper,
        jitter=lambda delay: delay / 2,
    ) as client:
        await client.request("GET", "https://source.example/records")

    assert delays == [1.5, 3.0]


@pytest.mark.asyncio
async def test_cancellation_propagates_without_retrying() -> None:
    entered_handler = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        entered_handler.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as client:
        task = asyncio.create_task(client.request("GET", "https://source.example/hang"))
        await entered_handler.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
