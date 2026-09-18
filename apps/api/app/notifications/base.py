from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models import NotificationEvent


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    retryable: bool = False
    error_code: str = "delivery_failed"


class NotificationChannel(Protocol):
    async def send(self, event: NotificationEvent) -> DeliveryResult: ...


class UnconfiguredChannel:
    async def send(self, event: NotificationEvent) -> DeliveryResult:
        return DeliveryResult(success=False, error_code="channel_not_configured")
