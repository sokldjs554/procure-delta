"""Official KONEPS service-tender contract; see docs/source-contracts.md."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.sources.base import AttachmentRef, DiscoveryPage, RawSourceRecord
from app.sources.http import ResilientHttpClient

SOURCE_CODE = "koneps-services"
BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
OPERATION = "getBidPblancListInfoServc"
DOCUMENT_HOST = "www.g2b.go.kr"
KST = timezone(timedelta(hours=9))
NORMALIZER = "koneps-services-v1"


def _text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    return str(value).strip() if value is not None else ""


def _identity(payload: Mapping[str, Any]) -> str:
    number, order = _text(payload, "bidNtceNo"), _text(payload, "bidNtceOrd")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,40}", number) or not re.fullmatch(r"\d{3}", order):
        raise ValueError("invalid official notice identity")
    return f"services:{number}:{order}"


def _date(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST).astimezone(UTC)


def map_payload(payload: Mapping[str, Any], source_record_id: str) -> dict[str, Any]:
    """Only called on a durable raw record; never mutate its upstream fields."""
    if _identity(payload) != source_record_id:
        raise ValueError("official identity differs from preserved envelope")
    kind = _text(payload, "ntceKindNm")
    mapping = {
        "title": "bidNtceNm", "buyer_name": "dminsttNm",
        "estimated_amount": "presmptPrce", "published_at": "bidNtceDt",
        "closes_at": "bidClseDt", "status": "ntceKindNm",
    }
    if not _text(payload, "dminsttNm"):
        mapping["buyer_name"] = "ntceInsttNm"
    result: dict[str, Any] = {key: _text(payload, field) or None for key, field in mapping.items()}
    for field in ("published_at", "closes_at"):
        result[field] = _date(result[field] or "")
    amount = result["estimated_amount"]
    if amount is not None:
        parsed = Decimal(amount)
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("invalid official estimated amount")
        result["estimated_amount"] = str(parsed)
    result.update(
        lifecycle_stage="amendment" if kind == "변경공고" else "tender",
        procurement_type="services", currency="KRW",
        effective_at=_date(_text(payload, "chgDt"))
        or _date(_text(payload, "rgstDt")) or result["published_at"],
        canonical_identity=f"services:{_text(payload, 'bidNtceNo')}",
        attachments=[ref.model_dump(exclude_none=True) for ref in attachment_refs(payload)],
        normalized_identifiers=[
            {"scheme": "koneps-service-notice", "value": _text(payload, "bidNtceNo")}
        ],
        evidence={key: [{"kind": "raw", "json_pointer": f"/{field}", "normalizer": NORMALIZER}]
                  for key, field in mapping.items() if result[key] is not None},
    )
    if amount is not None:
        # The official field definition states KRW; no currency inference from a title.
        result["evidence"]["currency"] = [{"kind": "raw", "json_pointer": "/presmptPrce",
                                            "normalizer": NORMALIZER}]
    return result


def attachment_refs(payload: Mapping[str, Any]) -> list[AttachmentRef]:
    refs = []
    for index in range(1, 11):
        url = _text(payload, f"ntceSpecDocUrl{index}")
        if url:
            refs.append(AttachmentRef(
                attachment_id=hashlib.sha256(url.encode()).hexdigest(),
                filename=_text(payload, f"ntceSpecFileNm{index}") or f"specification-{index}",
                url=url,
            ))
    return refs


class KonepsSourceAdapter:
    """Service notices with checkpointed registration/change-date discovery."""

    def __init__(self, *, service_key: str, client: ResilientHttpClient | None = None,
                 page_size: int = 100, lookback_days: int = 1) -> None:
        if not service_key.strip() or not 1 <= page_size <= 100 or not 1 <= lookback_days <= 30:
            raise ValueError("invalid KONEPS configuration")
        self._service_key = service_key
        self._client = client
        self._page_size = page_size
        self._lookback_days = lookback_days

    async def _request(self, parameters: dict[str, str]) -> dict[str, Any]:
        params = {"serviceKey": self._service_key, "type": "json",
                  "numOfRows": str(self._page_size), **parameters}
        try:
            if self._client is not None:
                response = await self._client.request(
                    "GET", f"{BASE_URL}/{OPERATION}", params=params
                )
            else:
                async with ResilientHttpClient() as client:
                    response = await client.request("GET", f"{BASE_URL}/{OPERATION}", params=params)
        except httpx.RequestError as error:
            # Transport messages can embed a URL containing the service key.
            # Retain the retry-relevant exception type, not the message or traceback chain.
            raise type(error)("KONEPS transport request failed", request=error.request) from None
        try:
            envelope = response.json()
        except ValueError:
            raise ValueError("invalid KONEPS JSON response") from None
        if not isinstance(envelope, dict) or not isinstance(envelope.get("response"), dict):
            raise ValueError("invalid KONEPS response envelope")
        data = envelope["response"]
        header = data.get("header")
        if not isinstance(header, dict) or "resultCode" not in header:
            raise ValueError("invalid KONEPS response header")
        if str(header["resultCode"]) != "00":
            # Do not echo resultMsg: an upstream server may repeat credentials there.
            raise ValueError("KONEPS API application error")
        body = data.get("body")
        if not isinstance(body, dict):
            raise ValueError("invalid KONEPS response body")
        return {**body, "_etag": response.headers.get("etag"),
                "_last_modified": response.headers.get("last-modified")}

    @staticmethod
    def _count(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError("invalid KONEPS pagination count")
        if isinstance(value, str) and not re.fullmatch(r"[0-9]+", value):
            raise ValueError("invalid KONEPS pagination count")
        result = int(value)
        if result < 0:
            raise ValueError("invalid KONEPS pagination count")
        return result

    def _validate_page(self, body: dict[str, Any], *, page: int, received: int) -> int:
        total = self._count(body.get("totalCount"))
        if self._count(body.get("pageNo")) != page:
            raise ValueError("inconsistent KONEPS pagination page number")
        if self._count(body.get("numOfRows")) != self._page_size:
            raise ValueError("inconsistent KONEPS pagination page size")
        expected = min(self._page_size, max(0, total - (page - 1) * self._page_size))
        if received != expected:
            raise ValueError("inconsistent KONEPS pagination item count")
        return total

    @staticmethod
    def _cursor_state(cursor: str) -> dict[str, Any]:
        try:
            state = json.loads(cursor)
            if not isinstance(state, dict) or state.get("mode") not in {"1", "3", "done"}:
                raise ValueError
            if type(state.get("page")) is not int or state["page"] < 1:
                raise ValueError
            for key in ("start", "end"):
                value = state.get(key)
                if not isinstance(value, str) or not re.fullmatch(r"[0-9]{12}", value):
                    raise ValueError
            start = datetime.strptime(state["start"], "%Y%m%d%H%M")
            end = datetime.strptime(state["end"], "%Y%m%d%H%M")
            if start > end or end - start > timedelta(days=30):
                raise ValueError
            return {"start": state["start"], "end": state["end"],
                    "mode": state["mode"], "page": state["page"]}
        except (ValueError, TypeError, KeyError):
            raise ValueError("invalid KONEPS cursor") from None

    @staticmethod
    def _records(body: dict[str, Any]) -> tuple[RawSourceRecord, ...]:
        items = body.get("items")
        if items in (None, ""):
            items = []
        if isinstance(items, dict):
            items = items.get("item", [])
            if isinstance(items, dict):
                items = [items]
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("invalid KONEPS items")
        return tuple(RawSourceRecord(
            source_record_id=_identity(item), raw_payload=item,
            source_url=f"{BASE_URL}/{OPERATION}", http_etag=body.get("_etag"),
            http_last_modified=body.get("_last_modified"),
        ) for item in items)

    async def discover(self, cursor: str | None) -> DiscoveryPage:
        now = datetime.now(KST).replace(second=0, microsecond=0)
        if cursor:
            state = self._cursor_state(cursor)
            if state["mode"] == "done":
                start = datetime.strptime(state["end"], "%Y%m%d%H%M").replace(tzinfo=KST)
                start -= timedelta(hours=1)
                state = {"start": start.strftime("%Y%m%d%H%M"),
                         "end": min(now, start + timedelta(days=1)).strftime("%Y%m%d%H%M"),
                         "mode": "1", "page": 1}
        else:
            state = {"start": (now - timedelta(days=self._lookback_days)).strftime("%Y%m%d%H%M"),
                     "end": now.strftime("%Y%m%d%H%M"), "mode": "1", "page": 1}
        body = await self._request({"inqryDiv": state["mode"], "inqryBgnDt": state["start"],
                                    "inqryEndDt": state["end"], "pageNo": str(state["page"])})
        records = self._records(body)
        total = self._validate_page(body, page=state["page"], received=len(records))
        if state["page"] * self._page_size < total:
            if not records:
                raise ValueError("KONEPS pagination made no progress")
            state["page"] += 1
        elif state["mode"] == "1":
            state.update(mode="3", page=1)
        else:
            state.update(mode="done", page=1)
        return DiscoveryPage(records=records, next_cursor=json.dumps(state, sort_keys=True))

    async def fetch_record(self, source_record_id: str) -> RawSourceRecord:
        pieces = source_record_id.split(":")
        if len(pieces) != 3 or pieces[0] != "services":
            raise ValueError("invalid official source record ID")
        if _identity({"bidNtceNo": pieces[1], "bidNtceOrd": pieces[2]}) != source_record_id:
            raise ValueError("invalid official source record ID")
        page = 1
        while page <= 100:
            body = await self._request(
                {"inqryDiv": "2", "bidNtceNo": pieces[1], "pageNo": str(page)}
            )
            records = self._records(body)
            total = self._validate_page(body, page=page, received=len(records))
            for record in records:
                if record.source_record_id == source_record_id:
                    return record
            if page * self._page_size >= total:
                raise KeyError("official record not found")
            page += 1
        raise ValueError("KONEPS lookup exceeded page bound")

    async def fetch_attachments(self, record: RawSourceRecord) -> list[AttachmentRef]:
        return attachment_refs(record.raw_payload)
