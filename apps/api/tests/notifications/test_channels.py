import json
from uuid import uuid4

import httpx
import pytest

from app.models import NotificationEvent


def event():
    return NotificationEvent(
        id=uuid4(),
        user_id="synthetic-owner",
        opportunity_id=uuid4(),
        channel="webhook",
        template_key="deadline_changed",
        dedupe_key="stable-key",
        payload_json={"title": "Synthetic", "evidence": "document"},
    )


@pytest.mark.asyncio
async def test_slack_format_uses_bounded_plain_text_without_mentions_or_raw_payload():
    from app.notifications.webhook import WebhookChannel

    item = event()
    item.payload_json = {
        "title": "<!channel> <@U123> & 공개 공고 " + "긴제목" * 2000,
        "private": "do-not-forward-canary",
    }
    requests = []

    def handle(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["mrkdwn"] is False
        assert payload["unfurl_links"] is False
        assert payload["unfurl_media"] is False
        assert "<!channel>" not in payload["text"]
        assert "<@U123>" not in payload["text"]
        assert "&lt;!channel&gt;" in payload["text"]
        block = payload["blocks"][0]["text"]
        assert block["type"] == "plain_text"
        assert "마감 변경" in block["text"]
        assert "공개 공고" in block["text"]
        assert str(item.opportunity_id) in block["text"]
        assert len(block["text"]) <= 3000
        assert b"do-not-forward-canary" not in request.content
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await WebhookChannel(
            "https://93.184.216.34/hook", client=client, payload_format="slack"
        ).send(item)
    assert result.success is True
    assert len(requests) == 1
    assert requests[0].headers["idempotency-key"] == "stable-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body,success,retryable",
    [
        (200, "ok", True, False),
        (200, "ok\n", True, False),
        (200, "invalid_payload secret-canary", False, False),
        (200, "", False, False),
        pytest.param(200, "x" * 10000, False, False, id="oversized-response"),
        (204, "", False, False),
        (400, "invalid_payload", False, False),
        (429, "rate_limited", False, True),
        (503, "unavailable", False, True),
        (302, "", False, False),
    ],
)
async def test_slack_accepts_only_explicit_success_and_keeps_bounded_retry_policy(
    status, body, success, retryable
):
    from app.notifications.webhook import WebhookChannel

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text=body))
    ) as client:
        result = await WebhookChannel(
            "https://93.184.216.34/hook", client=client, payload_format="slack"
        ).send(event())
    assert (result.success, result.retryable) == (success, retryable)
    assert "canary" not in (result.error_code or "")


def test_unknown_webhook_format_fails_configuration_instead_of_silent_fallback():
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(_env_file=None, notification_webhook_formats={"owner": "slcak"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,success,retryable",
    [
        (204, True, False),
        (400, False, False),
        (401, False, False),
        (429, False, True),
        (503, False, True),
        (302, False, False),
    ],
)
async def test_webhook_one_attempt_classifies_http_and_sends_idempotency(
    status, success, retryable
):
    from app.notifications.webhook import WebhookChannel

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, headers={"location": "http://127.0.0.1/secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await WebhookChannel(
            "https://93.184.216.34/hook?token=secret", client=client
        ).send(event())
    assert (result.success, result.retryable) == (success, retryable)
    assert len(requests) == 1
    assert requests[0].headers["idempotency-key"] == "stable-key"
    assert requests[0].extensions["timeout"]["connect"] == 5
    assert b'"event_id"' in requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/x",
        "https://127.0.0.1/x",
        "https://169.254.169.254/x",
        "https://user:pass@example.com/x",
        "https://[::1]/x",
    ],
)
async def test_webhook_rejects_unsafe_destinations_without_network(url):
    from app.notifications.webhook import WebhookChannel

    def unexpected(request):
        pytest.fail("Unsafe destination reached HTTP transport")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        result = await WebhookChannel(url, client=client).send(event())
    assert result.success is False and result.retryable is False
    assert result.error_code == "unsafe_destination"


@pytest.mark.asyncio
async def test_webhook_pins_public_dns_and_preserves_tls_host(monkeypatch):
    from app.notifications.webhook import WebhookChannel

    async def resolve(host):
        return ("93.184.216.34",)

    monkeypatch.setattr("app.documents.download._resolve_public_addresses", resolve)
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert (
            await WebhookChannel("https://hooks.example.com/secret", client=client).send(event())
        ).success
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "hooks.example.com"
    assert seen[0].extensions["sni_hostname"] == b"hooks.example.com"


@pytest.mark.asyncio
async def test_email_boundary_produces_email_message_with_stable_message_id():
    from app.notifications.base import DeliveryResult
    from app.notifications.email import EmailChannel

    messages = []

    class Transport:
        async def send_message(self, message, *, idempotency_key):
            messages.append((message, idempotency_key))
            return DeliveryResult(True)

    result = await EmailChannel(
        Transport(), sender="demo@example.invalid", recipient="synthetic@example.invalid"
    ).send(event())
    assert result.success
    message, key = messages[0]
    assert message["To"] == "synthetic@example.invalid"
    assert key == "stable-key"
    assert message["Message-ID"] == "<stable-key@procure-delta.invalid>"
    assert "Synthetic" in message.get_content()


@pytest.mark.asyncio
async def test_smtp_transport_connection_failure_is_retryable(monkeypatch):
    from email.message import EmailMessage

    from app.notifications.email import SmtpTransport

    def unavailable(*args, **kwargs):
        del args, kwargs
        raise OSError("synthetic SMTP connection failure")

    monkeypatch.setattr("app.notifications.email.smtplib.SMTP", unavailable)
    result = await SmtpTransport(
        host="smtp.example.invalid",
        starttls=False,
        timeout_seconds=0.2,
    ).send_message(EmailMessage(), idempotency_key="stable-key")
    assert result.success is False
    assert result.retryable is True
    assert result.error_code == "transport_error"
