"""Raw-preserving lookup for the official KONEPS contract-process service.

The public portal documents the request identifiers and service URL, but not the
nested response fields. This client therefore stores the response body as evidence
and extracts only identifier keys that are part of the published request contract.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.sources.http import ResilientHttpClient

BASE_URL = "https://apis.data.go.kr/1230000/ao/CntrctProcssIntgOpenService"
OPERATION = "getCntrctProcssIntgOpenServc"
IDENTIFIER_KEYS = (
    "bidNtceNo",
    "bidNtceOrd",
    "bfSpecRgstNo",
    "orderPlanNo",
    "prcrmntReqNo",
)
_PRIMARY_KEYS = (
    "bidNtceNo",
    "bfSpecRgstNo",
    "orderPlanNo",
    "prcrmntReqNo",
)


def _clean(value: str | None, *, name: str, max_length: int = 100) -> str | None:
    if value is None:
        return None
    result = value.strip()
    if not result or len(result) > max_length or not re.fullmatch(r"[0-9A-Za-z._-]+", result):
        raise ValueError(f"invalid contract-process {name}")
    return result


@dataclass(frozen=True, slots=True)
class ContractProcessQuery:
    inquiry_div: str
    bid_ntce_no: str | None = None
    bid_ntce_ord: str | None = None
    bf_spec_rgst_no: str | None = None
    order_plan_no: str | None = None
    prcrmnt_req_no: str | None = None

    def __post_init__(self) -> None:
        inquiry = self.inquiry_div.strip()
        if not re.fullmatch(r"[0-9]{1,3}", inquiry):
            raise ValueError("invalid contract-process inquiry_div")
        object.__setattr__(self, "inquiry_div", inquiry)
        values = {
            "bidNtceNo": _clean(self.bid_ntce_no, name="bidNtceNo", max_length=40),
            "bfSpecRgstNo": _clean(self.bf_spec_rgst_no, name="bfSpecRgstNo", max_length=40),
            "orderPlanNo": _clean(self.order_plan_no, name="orderPlanNo", max_length=80),
            "prcrmntReqNo": _clean(self.prcrmnt_req_no, name="prcrmntReqNo", max_length=40),
        }
        if sum(value is not None for value in values.values()) != 1:
            raise ValueError("exactly one official contract-process identifier is required")
        ordinal = _clean(self.bid_ntce_ord, name="bidNtceOrd", max_length=3)
        if ordinal is not None and values["bidNtceNo"] is None:
            raise ValueError("bidNtceOrd requires bidNtceNo")
        if ordinal is not None and not ordinal.isdigit():
            raise ValueError("invalid contract-process bidNtceOrd")
        object.__setattr__(self, "bid_ntce_no", values["bidNtceNo"])
        object.__setattr__(self, "bf_spec_rgst_no", values["bfSpecRgstNo"])
        object.__setattr__(self, "order_plan_no", values["orderPlanNo"])
        object.__setattr__(self, "prcrmnt_req_no", values["prcrmntReqNo"])
        object.__setattr__(self, "bid_ntce_ord", ordinal)

    def public_parameters(self) -> dict[str, str]:
        values = {
            "inqryDiv": self.inquiry_div,
            "bidNtceNo": self.bid_ntce_no,
            "bidNtceOrd": self.bid_ntce_ord,
            "bfSpecRgstNo": self.bf_spec_rgst_no,
            "orderPlanNo": self.order_plan_no,
            "prcrmntReqNo": self.prcrmnt_req_no,
        }
        return {key: value for key, value in values.items() if value is not None}

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.public_parameters(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ContractProcessPage:
    page_no: int
    num_rows: int
    total_count: int
    raw_body: dict[str, Any]
    body_sha256: str
    identifiers: dict[str, tuple[str, ...]]


def _count(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"invalid contract-process {name}")
    if isinstance(value, str) and not value.isdigit():
        raise ValueError(f"invalid contract-process {name}")
    result = int(value)
    if result < 0:
        raise ValueError(f"invalid contract-process {name}")
    return result


def extract_official_identifiers(value: object, *, max_nodes: int = 10_000) -> dict[str, tuple[str, ...]]:
    found: dict[str, set[str]] = {key: set() for key in IDENTIFIER_KEYS}
    stack: list[object] = [value]
    seen = 0
    while stack:
        current = stack.pop()
        seen += 1
        if seen > max_nodes:
            raise ValueError("contract-process response exceeds identifier traversal bound")
        if isinstance(current, Mapping):
            for key, item in current.items():
                if key in found and item is not None:
                    text = str(item).strip()
                    if 0 < len(text) <= 100 and re.fullmatch(r"[0-9A-Za-z._-]+", text):
                        found[key].add(text)
                if isinstance(item, (Mapping, list, tuple)):
                    stack.append(item)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            stack.extend(current)
    return {key: tuple(sorted(values)) for key, values in found.items() if values}


class KonepsContractProcessClient:
    def __init__(
        self,
        *,
        service_key: str,
        client: ResilientHttpClient | None = None,
        page_size: int = 100,
    ) -> None:
        if not service_key.strip() or not 1 <= page_size <= 999:
            raise ValueError("invalid KONEPS contract-process configuration")
        self._service_key = service_key
        self._client = client
        self._page_size = page_size

    async def _response_body(self, query: ContractProcessQuery, page_no: int) -> dict[str, Any]:
        if not 1 <= page_no <= 10_000:
            raise ValueError("invalid contract-process page number")
        params = {
            "serviceKey": self._service_key,
            "type": "json",
            "pageNo": str(page_no),
            "numOfRows": str(self._page_size),
            **query.public_parameters(),
        }
        try:
            if self._client is not None:
                response = await self._client.request(
                    "GET", f"{BASE_URL}/{OPERATION}", params=params
                )
            else:
                async with ResilientHttpClient() as client:
                    response = await client.request(
                        "GET", f"{BASE_URL}/{OPERATION}", params=params
                    )
        except httpx.RequestError as error:
            raise type(error)(
                "KONEPS contract-process transport request failed", request=error.request
            ) from None
        try:
            envelope = response.json()
        except ValueError:
            raise ValueError("invalid KONEPS contract-process JSON response") from None
        if not isinstance(envelope, dict) or not isinstance(envelope.get("response"), dict):
            raise ValueError("invalid KONEPS contract-process response envelope")
        data = envelope["response"]
        header = data.get("header")
        if not isinstance(header, dict) or str(header.get("resultCode", "")) != "00":
            raise ValueError("KONEPS contract-process API application error")
        body = data.get("body")
        if not isinstance(body, dict):
            raise ValueError("invalid KONEPS contract-process response body")
        return body

    async def fetch_page(
        self, query: ContractProcessQuery, *, page_no: int = 1
    ) -> ContractProcessPage:
        body = await self._response_body(query, page_no)
        observed_page = _count(body.get("pageNo"), name="pageNo")
        observed_rows = _count(body.get("numOfRows"), name="numOfRows")
        total = _count(body.get("totalCount"), name="totalCount")
        if observed_page != page_no or observed_rows != self._page_size:
            raise ValueError("inconsistent contract-process pagination metadata")
        encoded = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return ContractProcessPage(
            page_no=observed_page,
            num_rows=observed_rows,
            total_count=total,
            raw_body=body,
            body_sha256=hashlib.sha256(encoded).hexdigest(),
            identifiers=extract_official_identifiers(body),
        )

    async def fetch_all(
        self, query: ContractProcessQuery, *, max_pages: int = 3
    ) -> tuple[ContractProcessPage, ...]:
        if not 1 <= max_pages <= 10:
            raise ValueError("contract-process max_pages must be between 1 and 10")
        first = await self.fetch_page(query, page_no=1)
        pages = [first]
        required = max(1, (first.total_count + self._page_size - 1) // self._page_size)
        if required > max_pages:
            raise ValueError("contract-process result exceeds configured page bound")
        for page_no in range(2, required + 1):
            page = await self.fetch_page(query, page_no=page_no)
            if page.total_count != first.total_count:
                raise ValueError("contract-process totalCount changed during bounded lookup")
            pages.append(page)
        return tuple(pages)
