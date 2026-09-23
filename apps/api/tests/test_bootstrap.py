import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_health_live() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200


@pytest.mark.anyio
async def test_unexpected_error_is_captured_without_echoing_exception(monkeypatch) -> None:
    from fastapi import Request

    from app.main import unexpected_error

    seen = []
    monkeypatch.setattr("app.main.capture_tracked_exception", seen.append)
    request = Request({"type": "http", "method": "GET", "path": "/broken", "headers": []})
    error = RuntimeError("token=secret")

    response = await unexpected_error(request, error)

    assert response.status_code == 500
    assert seen == [error]
    assert b"token=secret" not in response.body
    assert b"Request could not be completed" in response.body
