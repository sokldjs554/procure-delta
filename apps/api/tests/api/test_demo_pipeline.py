import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_pipeline_scenario_list_is_public_read_only() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/demo/pipeline/scenarios")

    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [
        "new-opportunity",
        "amendment-eligibility-change",
        "failure-recovery",
    ]


@pytest.mark.asyncio
async def test_unknown_pipeline_scenario_returns_404_without_path_interpretation() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/demo/pipeline/scenarios/..%2F..%2Fetc%2Fpasswd"
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pipeline_scenario_always_exposes_honesty_boundary() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/demo/pipeline/scenarios/amendment-eligibility-change"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["synthetic"] is True
    assert body["source_scope"] == "packaged_fixture"
    assert all("measured_duration_ms" in stage for stage in body["stages"])
