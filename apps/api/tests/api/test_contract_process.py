from __future__ import annotations

import pytest

from app.models import ContractProcessSnapshot
from tests.api.test_opportunities import login


@pytest.mark.asyncio
async def test_contract_process_api_exposes_summary_without_raw_body_or_credentials(
    client,
    session,
    opportunities,
) -> None:
    await login(client)
    opportunity = opportunities[0]
    snapshot = ContractProcessSnapshot(
        opportunity_version_id=opportunity.current_version_id,
        inquiry_div="1",
        query_fingerprint="a" * 64,
        query_json={
            "inqryDiv": "1",
            "bidNtceNo": "R26BK99990001",
            "bidNtceOrd": "000",
        },
        page_no=1,
        total_count=1,
        response_sha256="b" * 64,
        raw_body_json={
            "numOfRows": "100",
            "pageNo": "1",
            "totalCount": "1",
            "sensitive_upstream_shape": {"unexpected": "preserved but private"},
        },
        identifiers_json={
            "bidNtceNo": ["R26BK99990001"],
            "bfSpecRgstNo": ["337425"],
        },
    )
    session.add(snapshot)
    await session.flush()

    response = await client.get(
        f"/api/v1/opportunities/{opportunity.id}/contract-process"
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["response_sha256"] == "b" * 64
    assert item["identifiers"]["bfSpecRgstNo"] == ["337425"]
    assert "raw_body_json" not in item
    assert "query_json" not in item
    assert "serviceKey" not in response.text


@pytest.mark.asyncio
async def test_contract_process_api_requires_existing_opportunity(client) -> None:
    from uuid import uuid4

    await login(client)
    response = await client.get(f"/api/v1/opportunities/{uuid4()}/contract-process")
    assert response.status_code == 404
