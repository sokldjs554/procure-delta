from __future__ import annotations

import asyncio
from html import escape
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from app.documents.download import UnsafeAttachmentURLError, _validated_target
from app.models import NotificationEvent
from app.notifications.base import DeliveryResult


class WebhookChannel:
    """One bounded HTTP attempt. Durable worker state owns the three-attempt budget.

    Destinations come only from operator configuration. DNS is pinned to a validated
    public address; redirects and environment proxies cannot bypass that boundary.
    Receivers must honor Idempotency-Key to dedupe an ambiguous external success.
    """

    def __init__(
        self, endpoint: str, *, client: httpx.AsyncClient | None = None,
        payload_format: Literal["generic", "slack"] = "generic",
    ) -> None:
        if payload_format not in {"generic", "slack"}:
            raise ValueError("unsupported webhook format")
        self._endpoint = endpoint
        self._client = client
        self._payload_format = payload_format

    def _payload(self, event: NotificationEvent) -> dict[str, Any]:
        if self._payload_format == "generic":
            return {
                "event_id": str(event.id), "template": event.template_key,
                "payload": event.payload_json,
            }
        label = {
            "new_high_relevance": "새 추천 공고", "watched_material_change": "관심 공고 변경",
            "deadline_changed": "마감 변경", "eligibility_changed": "참여 조건 변경",
            "outcome_published": "결과 공개",
        }.get(event.template_key, "공고 알림")
        title = event.payload_json.get("title")
        title = title[:2000] if isinstance(title, str) and title.strip() else "제목 미확인"
        text = (
            f"ProcureDelta · {label}\n{title}\n"
            f"공고 ID: {event.opportunity_id}\n알림 ID: {event.id}"
        )
        return {
            "text": escape(text, quote=False), "mrkdwn": False,
            "unfurl_links": False, "unfurl_media": False,
            "blocks": [{"type": "section", "text": {"type": "plain_text", "text": text}}],
        }

    async def send(self, event: NotificationEvent) -> DeliveryResult:
        try:
            async with asyncio.timeout(15):
                pinned, host = await _validated_target(
                    self._endpoint, urlsplit(self._endpoint).hostname or ""
                )
                if self._client is not None:
                    return await self._send(self._client, pinned, host, event)
                async with httpx.AsyncClient(trust_env=False) as client:
                    return await self._send(client, pinned, host, event)
        except (UnsafeAttachmentURLError, ValueError):
            return DeliveryResult(False, error_code="unsafe_destination")
        except (httpx.TransportError, OSError, TimeoutError):
            return DeliveryResult(False, retryable=True, error_code="transport_error")

    async def _send(
        self, client: httpx.AsyncClient, pinned: str, host: str, event: NotificationEvent
    ) -> DeliveryResult:
        async with client.stream(
            "POST",
            pinned,
            headers={"Host": host, "Idempotency-Key": event.dedupe_key},
            json=self._payload(event),
            extensions={"sni_hostname": host.encode()},
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
        ) as response:
            status = response.status_code
            if 200 <= status < 300:
                if self._payload_format == "slack":
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > 64:
                            return DeliveryResult(False, error_code="invalid_slack_response")
                        body.extend(chunk)
                    if status != 200 or bytes(body).strip() != b"ok":
                        return DeliveryResult(False, error_code="invalid_slack_response")
                return DeliveryResult(True)
            code = (
                "http_429"
                if status == 429
                else (
                    "http_5xx" if status >= 500 else "http_redirect" if status < 400 else "http_4xx"
                )
            )
            return DeliveryResult(False, retryable=status == 429 or status >= 500, error_code=code)
