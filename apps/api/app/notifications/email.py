"""Email-compatible boundary; no SMTP/provider transport is installed or enabled by default."""

import json
from email.message import EmailMessage
from typing import Protocol

from app.models import NotificationEvent
from app.notifications.base import DeliveryResult


class EmailTransport(Protocol):
    async def send_message(self, message: EmailMessage, *, idempotency_key: str) -> DeliveryResult:
        """Perform one attempt with explicit timeout; return classified failure without secrets."""
        ...


class EmailChannel:
    def __init__(self, transport: EmailTransport, *, sender: str, recipient: str) -> None:
        self._transport, self._sender, self._recipient = transport, sender, recipient

    async def send(self, event: NotificationEvent) -> DeliveryResult:
        message = EmailMessage()
        message["From"], message["To"] = self._sender, self._recipient
        message["Subject"] = f"ProcureDelta: {event.template_key}"
        message["Message-ID"] = f"<{event.dedupe_key}@procure-delta.invalid>"
        message.set_content(json.dumps(event.payload_json, ensure_ascii=False, indent=2))
        return await self._transport.send_message(message, idempotency_key=event.dedupe_key)
