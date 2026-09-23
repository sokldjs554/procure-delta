from __future__ import annotations

import httpx
import pytest

from app.sources.http import ResilientHttpClient
from app.sources.koneps_process import (
    BASE_URL,
    OPERATION,
    ContractProcessQuery,
    KonepsContractProcessClient,
)


def response_body(*, page_no: int = 1, num_rows: int = 2, total_count: int = 2) -> dict:
    return {
        "numOfRows": str(num_rows),
        "pageNo": str(page_no),
        "totalCount": str(total_count),
        "process": {
            "preSpecification": {"bfSpecRgstNo": "337425"},
            "tender": {
                "bidNtceNo": "R26BK99990001",
                "bidNtceOrd": "000",
            },
            "contracts": [
                {
                    "bidNtceNo": "R26BK99990001",
                    "orderPlanNo": "2-1-2026-1192266-000001",
                    "prcrmntReqNo": "26GA0289",
                }
            ],
        },
    }


@pytest.mark.asyncio
async def test_contract_process_request_uses_official_url_and_preserves_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "정상"},
                    "body": response_body(),
                }
            },
        )

    async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as http:
        client = KonepsContractProcessClient(
            service_key="synthetic+key=",
            client=http,
            page_size=2,
        )
        query = ContractProcessQuery(
            inquiry_div="1",
            bid_ntce_no="R26BK99990001",
            bid_ntce_ord="000",
        )
        page = await client.fetch_page(query)

    assert seen[0].url.path == (
        "/1230000/ao/CntrctProcssIntgOpenService/getCntrctProcssIntgOpenServc"
    )
    assert str(seen[0].url.copy_with(query=None)) == f"{BASE_URL}/{OPERATION}"
    assert seen[0].url.params["serviceKey"] == "synthetic+key="
    assert seen[0].url.params["type"] == "json"
    assert seen[0].url.params["inqryDiv"] == "1"
    assert seen[0].url.params["bidNtceNo"] == "R26BK99990001"
    assert seen[0].url.params["bidNtceOrd"] == "000"
    assert page.raw_body == response_body()
    assert page.identifiers == {
        "bidNtceNo": ("R26BK99990001",),
        "bidNtceOrd": ("000",),
        "bfSpecRgstNo": ("337425",),
        "orderPlanNo": ("2-1-2026-1192266-000001",),
        "prcrmntReqNo": ("26GA0289",),
    }
    assert "synthetic+key" not in page.body_sha256
    assert "synthetic+key" not in query.fingerprint()


def test_contract_process_query_requires_one_official_identifier() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ContractProcessQuery(inquiry_div="1")
    with pytest.raises(ValueError, match="exactly one"):
        ContractProcessQuery(
            inquiry_div="1",
            bid_ntce_no="R26BK99990001",
            bf_spec_rgst_no="337425",
        )
    with pytest.raises(ValueError, match="requires bidNtceNo"):
        ContractProcessQuery(inquiry_div="1", bf_spec_rgst_no="337425", bid_ntce_ord="000")
    with pytest.raises(ValueError, match="inquiry_div"):
        ContractProcessQuery(inquiry_div="not-a-code", bid_ntce_no="R26BK99990001")


@pytest.mark.asyncio
async def test_contract_process_fetch_all_is_bounded_and_checks_total_count() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page_no = int(request.url.params["pageNo"])
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00"},
                    "body": response_body(page_no=page_no, num_rows=1, total_count=2),
                }
            },
        )

    async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as http:
        client = KonepsContractProcessClient(
            service_key="synthetic-key",
            client=http,
            page_size=1,
        )
        pages = await client.fetch_all(
            ContractProcessQuery(inquiry_div="1", bid_ntce_no="R26BK99990001"),
            max_pages=2,
        )
    assert [page.page_no for page in pages] == [1, 2]
    assert [request.url.params["pageNo"] for request in requests] == ["1", "2"]

    async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as http:
        client = KonepsContractProcessClient(
            service_key="synthetic-key",
            client=http,
            page_size=1,
        )
        with pytest.raises(ValueError, match="page bound"):
            await client.fetch_all(
                ContractProcessQuery(inquiry_div="1", bid_ntce_no="R26BK99990001"),
                max_pages=1,
            )


@pytest.mark.asyncio
async def test_contract_process_rejects_application_errors_without_echoing_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "response": {
                    "header": {
                        "resultCode": "20",
                        "resultMsg": "permission denied serviceKey=secret-value",
                    },
                    "body": {},
                }
            },
        )

    async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as http:
        client = KonepsContractProcessClient(service_key="secret-value", client=http)
        with pytest.raises(ValueError, match="application error") as captured:
            await client.fetch_page(
                ContractProcessQuery(inquiry_div="1", bid_ntce_no="R26BK99990001")
            )
    assert "secret-value" not in str(captured.value)
