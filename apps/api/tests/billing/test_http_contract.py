import hashlib
import hmac
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api.billing import router
from app.billing.service import BillingResult
from app.config import Settings, get_settings
from app.db import get_session

SECRET = "whsec_synthetic_http_only"
FIXTURE = Path(__file__).parent / "fixtures" / "basil_paid.json"


class SessionProbe:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def application(enabled=True):
    app = FastAPI()
    app.include_router(router)
    probe = SessionProbe()
    settings = Settings(_env_file=None, billing_sandbox_enabled=enabled,
                        billing_sandbox_scope="stable-merchant-sandbox",
                        billing_stripe_webhook_secret=SECRET)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: probe
    return app, probe


def signature(body):
    timestamp = str(int(time.time()))
    digest = hmac.new(SECRET.encode(), timestamp.encode() + b"." + body,
                      hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


@pytest.mark.asyncio
async def test_disabled_route_does_not_process_or_commit():
    app, probe = application(False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/billing/stripe", content=b"private")
    assert response.status_code == 404
    assert probe.commits == 0


@pytest.mark.asyncio
async def test_bad_signature_precedes_json_decoding_and_has_safe_error(monkeypatch):
    app, probe = application()

    def do_not_decode(_):
        raise AssertionError("unverified JSON reached parser")

    monkeypatch.setattr("app.api.billing.parse_event", do_not_decode)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/billing/stripe", content=b"private@example.invalid",
                                     headers={"Stripe-Signature": "private-signature"})
    assert response.status_code == 400
    assert "private" not in response.text
    assert SECRET not in response.text
    assert probe.commits == 0


@pytest.mark.asyncio
async def test_stream_limit_and_duplicate_headers():
    app, probe = application()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = b" " * (256 * 1024 + 1)
        response = await client.post("/api/v1/billing/stripe", content=body,
                                     headers={"Stripe-Signature": signature(body)})
        assert response.status_code == 413
        response = await client.post("/api/v1/billing/stripe", content=b"{}", headers=[
            ("Stripe-Signature", signature(b"{}")), ("Stripe-Signature", signature(b"{}"))])
        assert response.status_code == 400
    assert probe.commits == 0


@pytest.mark.asyncio
async def test_valid_signature_commits_after_processing_explicit_server_scope(monkeypatch):
    app, probe = application()

    async def process(session, *, scope, event):
        assert session is probe
        assert scope == "stable-merchant-sandbox"
        assert event.invoice.customer_id == "cus_synthetic"
        assert probe.commits == 0
        return BillingResult("applied", credited=True)

    monkeypatch.setattr("app.api.billing.process_event", process)
    body = FIXTURE.read_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/billing/stripe", content=body,
                                     headers={"Stripe-Signature": signature(body)})
    assert response.status_code == 200
    assert response.json()["credited"] is True
    assert probe.commits == 1


def test_settings_are_disabled_by_default_and_empty_compose_values_normalize():
    settings = Settings(_env_file=None, billing_sandbox_scope="", billing_stripe_webhook_secret="")
    assert not settings.billing_sandbox_enabled
    assert settings.billing_sandbox_scope is None
    assert settings.billing_stripe_webhook_secret is None
    with pytest.raises(ValidationError):
        Settings(_env_file=None, billing_sandbox_enabled=True, billing_sandbox_scope="",
                 billing_stripe_webhook_secret="")
