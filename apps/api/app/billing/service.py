"""One transaction per signed event; caller owns commit/rollback.

Lock order is event, invoice, credit account. PostgreSQL advisory locks serialize
missing records, while unique constraints remain the durable replay fences.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.contract import (
    BillingInputError,
    SandboxEvent,
    require_id,
    require_integer,
    require_scope,
)
from app.credits import grant_credits
from app.models import (
    BillingCustomerMapping,
    BillingEventObservation,
    BillingInvoiceApplication,
    BillingPricePolicy,
    CreditAccount,
)


class BillingConflict(ValueError):
    def __init__(self) -> None:
        super().__init__("Sandbox billing identity conflicts with an existing record")


@dataclass(frozen=True, slots=True)
class BillingResult:
    status: str
    credited: bool = False
    duplicate: bool = False
    review_reason: str | None = None


async def _lock(session: AsyncSession, kind: str, scope: str, identity: str) -> None:
    digest = hashlib.sha256(f"billing:{kind}:{scope}:{identity}".encode()).digest()
    key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    await session.execute(select(func.pg_advisory_xact_lock(key)))


async def register_customer(
    session: AsyncSession, *, scope: str, customer_id: str,
) -> BillingCustomerMapping:
    require_scope(scope)
    require_id(customer_id, "cus")
    await _lock(session, "customer", scope, customer_id)
    existing = await session.scalar(select(BillingCustomerMapping).where(
        BillingCustomerMapping.scope == scope, BillingCustomerMapping.customer_id == customer_id))
    if existing is not None:
        return existing
    # Operator cannot bind an existing account or a demo/real identity.
    owner = "billing-sandbox:" + hashlib.sha256(f"{scope}:{customer_id}".encode()).hexdigest()
    if await session.scalar(select(CreditAccount.id).where(CreditAccount.owner_user_id == owner)):
        raise BillingConflict()
    account = CreditAccount(owner_user_id=owner, account_kind="billing_sandbox")
    session.add(account)
    await session.flush()
    mapping = BillingCustomerMapping(scope=scope, customer_id=customer_id, account_id=account.id)
    session.add(mapping)
    await session.flush()
    return mapping


async def register_price(
    session: AsyncSession, *, scope: str, price_id: str, currency: str, amount: int, units: int,
) -> BillingPricePolicy:
    require_scope(scope)
    require_id(price_id, "price")
    require_integer(amount, minimum=1)
    require_integer(units, minimum=1, maximum=1_000_000)
    if not re.fullmatch(r"[a-z]{3}", currency, re.ASCII):
        raise BillingInputError()
    await _lock(session, "price", scope, price_id)
    existing = await session.scalar(select(BillingPricePolicy).where(
        BillingPricePolicy.scope == scope, BillingPricePolicy.price_id == price_id))
    if existing is not None:
        if (existing.currency, existing.amount, existing.credit_units) != (currency, amount, units):
            raise BillingConflict()
        return existing
    policy = BillingPricePolicy(scope=scope, price_id=price_id, currency=currency,
                                amount=amount, credit_units=units)
    session.add(policy)
    await session.flush()
    return policy


async def process_event(session: AsyncSession, *, scope: str, event: SandboxEvent) -> BillingResult:
    require_scope(scope)
    await _lock(session, "event", scope, event.event_id)
    previous = await session.scalar(select(BillingEventObservation).where(
        BillingEventObservation.scope == scope, BillingEventObservation.event_id == event.event_id))
    if previous is not None:
        if previous.event_digest != event.digest:
            raise BillingConflict()
        return BillingResult(previous.outcome, duplicate=True, review_reason=previous.review_reason)

    application: BillingInvoiceApplication | None = None
    status, review = "observed", event.review_reason
    invoice = event.invoice
    if invoice is not None:
        await _lock(session, "invoice", scope, invoice.invoice_id)
        application = await session.scalar(select(BillingInvoiceApplication).where(
            BillingInvoiceApplication.scope == scope,
            BillingInvoiceApplication.invoice_id == invoice.invoice_id))
        if application is not None:
            if application.invoice_digest != invoice.digest:
                raise BillingConflict()
            status = "duplicate"
        else:
            mapping = await session.scalar(select(BillingCustomerMapping).where(
                BillingCustomerMapping.scope == scope,
                BillingCustomerMapping.customer_id == invoice.customer_id))
            policy = await session.scalar(select(BillingPricePolicy).where(
                BillingPricePolicy.scope == scope, BillingPricePolicy.price_id == invoice.price_id))
            if mapping is None:
                review = "unmapped_customer"
            elif policy is None:
                review = "unmapped_price"
            elif (policy.currency, policy.amount) != (invoice.currency, invoice.amount):
                review = "price_policy_mismatch"
            else:
                account = await session.get(CreditAccount, mapping.account_id)
                if account is None:
                    raise BillingConflict()
                mutation = await grant_credits(
                    session, owner_user_id=account.owner_user_id, amount=policy.credit_units,
                    expected_kind="billing_sandbox",
                    idempotency_key="sandbox-invoice:" + invoice.invoice_id,
                    reference_type="sandbox_invoice", reference_key=invoice.invoice_id,
                    metadata={"scope": scope, "policy_id": str(policy.id)},
                )
                if not mutation.applied or mutation.account.id != mapping.account_id:
                    # A ledger entry without its atomic application is corruption,
                    # not a reason to manufacture a receipt for an operator grant.
                    raise BillingConflict()
                application = BillingInvoiceApplication(
                    scope=scope, invoice_id=invoice.invoice_id, invoice_digest=invoice.digest,
                    account_id=mapping.account_id, policy_id=policy.id,
                    credit_units=policy.credit_units, ledger_entry_id=mutation.ledger.id,
                    facts_json=asdict(invoice))
                session.add(application)
                await session.flush()
                status = "applied"
    if review is not None:
        status = "review"
    observation = BillingEventObservation(
        scope=scope, event_id=event.event_id, event_type=event.event_type,
        event_created=event.created, object_id=event.object_id, customer_id=event.customer_id,
        event_digest=event.digest, facts_json=event.facts, outcome=status, review_reason=review,
        application_id=application.id if application else None)
    session.add(observation)
    await session.flush()
    return BillingResult(status, credited=status == "applied", duplicate=status == "duplicate",
                         review_reason=review)
