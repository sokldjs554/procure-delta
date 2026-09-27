"""Real PostgreSQL concurrency/rollback checks; provider traffic is always synthetic."""
import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.contract import parse_event
from app.billing.service import BillingConflict, process_event, register_customer, register_price
from app.config import Settings
from app.credits import (
    CreditAccountKindError,
    commit_credits,
    grant_credits,
    refund_credits,
    reserve_credits,
)
from app.models import (
    BillingCustomerMapping,
    BillingEventObservation,
    BillingInvoiceApplication,
    CreditAccount,
    CreditLedgerEntry,
    CreditReservation,
)
from app.workers.extraction import extract_version
from tests.credits.test_extraction_integration import ControlledProvider
from tests.extraction.test_persistence import seeded as _seeded

seeded = _seeded
SCOPE = "synthetic-merchant-stable"
FIXTURE = Path(__file__).parent / "fixtures" / "basil_paid.json"


def payload(event_id="evt_synthetic_paid", invoice_id="in_synthetic_cycle"):
    raw = json.loads(FIXTURE.read_bytes())
    raw["id"] = event_id
    raw["data"]["object"]["id"] = invoice_id
    return raw


def parsed(raw=None):
    return parse_event(json.dumps(payload() if raw is None else raw).encode())


async def setup(factory):
    async with factory.begin() as session:
        mapping = await register_customer(session, scope=SCOPE, customer_id="cus_synthetic")
        await register_price(session, scope=SCOPE, price_id="price_synthetic", currency="usd",
                             amount=1000, units=10)
        account = await session.get(CreditAccount, mapping.account_id)
        return account.owner_user_id


async def deliver(factory, raw=None):
    async with factory.begin() as session:
        return await process_event(session, scope=SCOPE, event=parsed(raw))


async def counts(factory):
    async with factory() as session:
        return tuple([await session.scalar(select(func.count()).select_from(model)) for model in (
            CreditLedgerEntry, BillingInvoiceApplication, BillingEventObservation)])


@pytest.mark.asyncio
async def test_response_loss_and_distinct_event_replays_apply_once(worker_session_factory):
    owner = await setup(worker_session_factory)
    assert (await deliver(worker_session_factory)).credited
    # Receipt is committed before response delivery. A lost response is just a replay.
    assert (await deliver(worker_session_factory)).duplicate
    assert (await deliver(worker_session_factory, payload("evt_second"))).duplicate
    assert await counts(worker_session_factory) == (1, 1, 2)
    async with worker_session_factory() as session:
        account = await session.scalar(select(CreditAccount).where(
            CreditAccount.owner_user_id == owner))
        application = await session.scalar(select(BillingInvoiceApplication))
        assert account.available_credits == application.credit_units == 10
        assert application.account_id == account.id
        assert await session.scalar(select(CreditReservation.id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("same_event", [True, False])
async def test_concurrent_same_invoice_grants_once(worker_session_factory, same_event):
    await setup(worker_session_factory)
    results = await asyncio.gather(*[
        deliver(worker_session_factory, payload("evt_same" if same_event else f"evt_{i}"))
        for i in range(8)])
    assert sum(result.credited for result in results) == 1
    assert await counts(worker_session_factory) == (1, 1, 1 if same_event else 8)


@pytest.mark.asyncio
async def test_concurrent_different_invoices_preserve_account_balance(worker_session_factory):
    await setup(worker_session_factory)
    await asyncio.gather(*[deliver(worker_session_factory, payload(f"evt_{i}", f"in_{i}"))
                           for i in range(8)])
    async with worker_session_factory() as session:
        assert await session.scalar(select(CreditAccount.available_credits)) == 80
    assert await counts(worker_session_factory) == (8, 8, 8)


@pytest.mark.asyncio
async def test_same_event_cannot_concurrently_fund_two_invoices(worker_session_factory):
    await setup(worker_session_factory)
    async with worker_session_factory.begin() as session:
        await register_customer(session, scope=SCOPE, customer_id="cus_other")
    other = payload("evt_same", "in_two")
    other["data"]["object"]["customer"] = "cus_other"
    results = await asyncio.gather(
        deliver(worker_session_factory, payload("evt_same", "in_one")),
        deliver(worker_session_factory, other), return_exceptions=True)
    assert sum(isinstance(result, BillingConflict) for result in results) == 1
    assert await counts(worker_session_factory) == (1, 1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["event", "invoice"])
async def test_conflicting_replay_cannot_remap_or_change_facts(worker_session_factory, conflict):
    await setup(worker_session_factory)
    await deliver(worker_session_factory)
    raw = payload() if conflict == "event" else payload("evt_distinct")
    raw["data"]["object"]["customer"] = "cus_other"
    async with worker_session_factory.begin() as session:
        await register_customer(session, scope=SCOPE, customer_id="cus_other")
    with pytest.raises(BillingConflict):
        await deliver(worker_session_factory, raw)
    assert await counts(worker_session_factory) == (1, 1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["after_grant", "before_receipt"])
async def test_grant_application_receipt_roll_back_together(
    worker_session_factory, monkeypatch, failure_point,
):
    import app.billing.service as service

    await setup(worker_session_factory)
    original_grant = service.grant_credits
    original_flush = AsyncSession.flush
    injected = []

    async def fail_grant(*args, **kwargs):
        await original_grant(*args, **kwargs)
        injected.append("after_grant")
        raise RuntimeError("injected before application")

    async def fail_receipt(session, *args, **kwargs):
        if any(isinstance(row, BillingEventObservation) for row in session.new):
            # No ORM autoflush here: verify the two earlier writes reached the
            # transaction before refusing the pending observation's flush.
            for model in (CreditLedgerEntry, BillingInvoiceApplication):
                assert await session.scalar(select(func.count()).select_from(model)
                                            .execution_options(autoflush=False)) == 1
            injected.append("before_receipt")
            raise RuntimeError("injected before receipt")
        return await original_flush(session, *args, **kwargs)

    if failure_point == "after_grant":
        monkeypatch.setattr(service, "grant_credits", fail_grant)
    else:
        monkeypatch.setattr(AsyncSession, "flush", fail_receipt)
    with pytest.raises(RuntimeError):
        await deliver(worker_session_factory)
    assert injected == [failure_point]
    assert await counts(worker_session_factory) == (0, 0, 0)
    async with worker_session_factory() as session:
        assert await session.scalar(select(CreditAccount.available_credits)) == 0
    monkeypatch.setattr(service, "grant_credits", original_grant)
    monkeypatch.setattr(AsyncSession, "flush", original_flush)
    assert (await deliver(worker_session_factory)).credited


@pytest.mark.asyncio
async def test_failed_paid_and_late_failed_are_observations_not_entitlement(worker_session_factory):
    await setup(worker_session_factory)
    failed = payload("evt_failed")
    failed["type"] = "invoice.payment_failed"
    failed["data"]["object"]["status"] = "open"
    assert (await deliver(worker_session_factory, failed)).status == "observed"
    assert (await deliver(worker_session_factory)).credited
    failed["id"] = "evt_failed_late"
    assert (await deliver(worker_session_factory, failed)).status == "observed"
    for number, kind in enumerate(("deleted", "created", "updated")):
        raw = payload(f"evt_subscription_{number}")
        raw["type"] = f"customer.subscription.{kind}"
        raw["data"]["object"] = {"id": "sub_synthetic", "object": "subscription",
                                   "livemode": False, "customer": "cus_synthetic",
                                   "status": "canceled" if kind == "deleted" else "active"}
        assert (await deliver(worker_session_factory, raw)).status == "observed"
    assert await counts(worker_session_factory) == (1, 1, 6)


@pytest.mark.asyncio
async def test_metadata_cannot_choose_owner_or_units_and_pii_is_not_retained(
    worker_session_factory,
):
    await setup(worker_session_factory)
    raw = payload()
    raw["data"]["object"]["metadata"] = {"owner": "victim", "units": 500000}
    raw["data"]["object"]["customer_email"] = "private@example.invalid"
    await deliver(worker_session_factory, raw)
    async with worker_session_factory() as session:
        assert await session.scalar(select(CreditAccount.available_credits)) == 10
        event = await session.scalar(select(BillingEventObservation))
        application = await session.scalar(select(BillingInvoiceApplication))
        assert "private" not in json.dumps(event.facts_json)
        assert "victim" not in json.dumps(application.facts_json)


@pytest.mark.asyncio
async def test_signed_http_webhook_and_postgresql_ledger_are_connected(
    worker_session_factory, monkeypatch,
):
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings
    from app.db import get_session
    from app.main import app
    from tests.billing.test_http_contract import SECRET, signature

    await setup(worker_session_factory)
    settings = Settings(
        _env_file=None, billing_sandbox_enabled=True, billing_sandbox_scope=SCOPE,
        billing_stripe_webhook_secret=SECRET)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)

    async def database_session():
        async with worker_session_factory() as session:
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_session, database_session)
    body = FIXTURE.read_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/v1/billing/stripe", content=body,
                                  headers={"Stripe-Signature": signature(body)})
        assert first.status_code == 200
        assert first.json()["credited"] is True
        replay = await client.post("/api/v1/billing/stripe", content=body,
                                   headers={"Stripe-Signature": signature(body)})
        assert replay.status_code == 200
        assert replay.json()["credited"] is False
        assert replay.json()["duplicate"] is True
        conflicting = payload()
        conflicting["data"]["object"]["customer"] = "cus_other"
        conflict_body = json.dumps(conflicting).encode()
        conflict = await client.post("/api/v1/billing/stripe", content=conflict_body,
                                     headers={"Stripe-Signature": signature(conflict_body)})
        assert conflict.status_code == 409
    assert await counts(worker_session_factory) == (1, 1, 1)
    async with worker_session_factory() as session:
        assert await session.scalar(select(CreditAccount.available_credits)) == 10


@pytest.mark.asyncio
async def test_unmapped_review_is_immutable_and_does_not_reserve_invoice(worker_session_factory):
    result = await deliver(worker_session_factory)
    assert result.review_reason == "unmapped_customer"
    await setup(worker_session_factory)
    assert (await deliver(worker_session_factory)).review_reason == "unmapped_customer"
    assert (await deliver(worker_session_factory, payload("evt_new_delivery"))).credited
    assert await counts(worker_session_factory) == (1, 1, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [
    "UPDATE credit_accounts SET account_kind = 'internal_budget'",
    "UPDATE credit_accounts SET owner_user_id = 'renamed-sandbox'",
    "DELETE FROM billing_customer_mappings",
    "UPDATE billing_customer_mappings SET customer_id = 'cus_other'",
    "DELETE FROM billing_price_policies",
    "UPDATE billing_price_policies SET credit_units = 999",
    "DELETE FROM billing_invoice_applications",
    "UPDATE billing_invoice_applications SET credit_units = 999",
    "DELETE FROM billing_event_observations",
    "UPDATE billing_event_observations SET outcome = 'review'",
])
async def test_identity_and_receipts_are_immutable_at_database_boundary(
    worker_session_factory, command,
):
    await setup(worker_session_factory)
    await deliver(worker_session_factory)
    with pytest.raises(DBAPIError):
        async with worker_session_factory.begin() as session:
            await session.execute(text(command))
    assert await counts(worker_session_factory) == (1, 1, 1)


@pytest.mark.asyncio
async def test_operator_cannot_rewrite_policy_or_bind_internal_account(worker_session_factory):
    await setup(worker_session_factory)
    with pytest.raises(BillingConflict):
        async with worker_session_factory.begin() as session:
            await register_price(session, scope=SCOPE, price_id="price_synthetic", currency="usd",
                                 amount=1000, units=20)
    with pytest.raises(DBAPIError):
        async with worker_session_factory.begin() as session:
            account = CreditAccount(owner_user_id="internal")
            session.add(account)
            await session.flush()
            session.add(BillingCustomerMapping(scope=SCOPE, customer_id="cus_internal",
                                              account_id=account.id))
            await session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["grant", "reserve", "commit", "refund"])
async def test_normal_credit_operations_cannot_use_sandbox(worker_session_factory, operation):
    owner = await setup(worker_session_factory)
    await deliver(worker_session_factory)
    with pytest.raises(CreditAccountKindError):
        async with worker_session_factory.begin() as session:
            kwargs = {"owner_user_id": owner, "idempotency_key": "normal-attempt"}
            if operation in {"grant", "reserve"}:
                kwargs.update(amount=1, reference_type="normal", reference_key="test")
            if operation != "grant":
                kwargs["reservation_key"] = "normal-attempt"
            target = {"grant": grant_credits, "reserve": reserve_credits,
                      "commit": commit_credits, "refund": refund_credits}[operation]
            await target(session, **kwargs)


@pytest.mark.asyncio
async def test_hosted_account_misconfiguration_blocks_provider(
    seeded, worker_session_factory, monkeypatch,
):
    owner = await setup(worker_session_factory)
    await deliver(worker_session_factory)
    settings = Settings(_env_file=None, extraction_mode="hosted", extraction_credits_enabled=True,
                        extraction_credit_account=owner, extraction_credit_units=2)
    monkeypatch.setattr("app.workers.extraction.get_settings", lambda: settings)
    provider = ControlledProvider()
    result = await extract_version(
        {"session_factory": worker_session_factory, "extractor": provider}, str(seeded))
    assert result["status"] == "dead_lettered"
    assert provider.calls == 0
    async with worker_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(CreditReservation)) == 0
        assert await session.scalar(select(CreditAccount.available_credits)) == 10
