import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_evaluation_summary_separates_provider_contract_from_hosted_model() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/evaluation/summary")

    assert response.status_code == 200
    body = response.json()

    assert body["routes"]["provider_contract_all"]["status"] == "measured"
    assert body["routes"]["provider_contract_all"]["hosted_calls"] == 10
    assert body["routes"]["provider_contract_gated"]["hosted_calls"] == 5
    assert body["provider_contract_optimization"]["call_reduction_rate"] == 0.5
    assert body["provider_contract_optimization"]["token_reduction_rate"] == 0.5
    assert body["routes"]["provider_contract_all"]["reported_cost"] is None

    assert body["hosted_evaluated"] is False
    assert body["routes"]["hosted_all"]["status"] == "not_run"
    assert body["routes"]["hosted_gated"]["status"] == "not_run"

    serialized = response.text
    assert "trusted_fields" not in serialized
    assert '"rows"' not in serialized
