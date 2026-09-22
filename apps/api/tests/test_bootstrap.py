import logging
import re

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from app.main import app, unexpected_error
from app.observability import REQUEST_ID_HEADER


@pytest.mark.anyio
async def test_health_live(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="procure_delta.http")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    request_id = response.headers[REQUEST_ID_HEADER]
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)

    records = [
        record for record in caplog.records if record.getMessage() == "http_request_completed"
    ]
    assert records
    record = records[-1]
    assert record.request_id == request_id
    assert record.method == "GET"
    assert record.path == "/health/live"
    assert record.status == 200
    assert record.duration_ms >= 0


@pytest.mark.anyio
async def test_unexpected_error_is_generic_and_keeps_request_id() -> None:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/synthetic-failure",
            "raw_path": b"/synthetic-failure",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
        }
    )
    request.state.request_id = "a" * 32

    response = await unexpected_error(request, RuntimeError("sensitive synthetic detail"))

    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "a" * 32
    assert b"sensitive synthetic detail" not in response.body
    assert b"Request could not be completed" in response.body
