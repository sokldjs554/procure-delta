from __future__ import annotations

import asyncio
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

    def __init__(self, endpoint: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._endpoint = endpoint
        self._client = client

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
            json={
                "event_id": str(event.id),
                "template": event.template_key,
                "payload": event.payload_json,
            },
            extensions={"sni_hostname": host.encode()},
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
        ) as response:
            status = response.status_code
            if 200 <= status < 300:
                return DeliveryResult(True)
            code = (
                "http_429"
                if status == 429
                else (
                    "http_5xx" if status >= 500 else "http_redirect" if status < 400 else "http_4xx"
                )
            )
            return DeliveryResult(False, retryable=status == 429 or status >= 500, error_code=code)
