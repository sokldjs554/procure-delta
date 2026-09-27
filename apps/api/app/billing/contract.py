"""Bounded Stripe Basil snapshot and raw-body signature contracts.

Only allowlisted facts leave this module. Verification must precede parsing at the
HTTP boundary; these pure functions also support offline synthetic contract tests.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

API_VERSION = "2025-03-31.basil"
MAX_BODY_BYTES = 256 * 1024
MAX_SIGNATURE_LENGTH = 4096
MAX_INTEGER = 2_147_483_647
MAX_TIMESTAMP = 253_402_300_799
ID_PATTERN = re.compile(r"[a-z][a-z0-9]*_[A-Za-z0-9_]{1,190}\Z", re.ASCII)
SCOPE_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z", re.ASCII)


class BillingInputError(ValueError):
    def __init__(self) -> None:
        super().__init__("Invalid sandbox billing input")


@dataclass(frozen=True, slots=True)
class InvoiceFacts:
    invoice_id: str
    customer_id: str
    subscription_id: str
    price_id: str
    currency: str
    amount: int
    quantity: int
    period_start: int
    period_end: int
    billing_reason: str

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class SandboxEvent:
    event_id: str
    event_type: str
    created: int
    object_id: str
    customer_id: str | None
    digest: str
    facts: dict[str, Any]
    invoice: InvoiceFacts | None
    review_reason: str | None


def canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def require_scope(value: str) -> str:
    if not isinstance(value, str) or not SCOPE_PATTERN.fullmatch(value):
        raise BillingInputError()
    return value


def require_id(value: object, prefix: str | None = None) -> str:
    if (not isinstance(value, str) or len(value) > 200 or not ID_PATTERN.fullmatch(value)
            or (prefix is not None and not value.startswith(prefix + "_"))):
        raise BillingInputError()
    return value


def require_integer(value: object, *, minimum: int = 0, maximum: int = MAX_INTEGER) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise BillingInputError()
    return value


def verify_signature(body: bytes, header: str, secret: str, *, now: float | None = None) -> None:
    if (len(body) > MAX_BODY_BYTES or not header or len(header) > MAX_SIGNATURE_LENGTH
            or not secret):
        raise BillingInputError()
    timestamps: list[str] = []
    signatures: list[str] = []
    for component in header.split(","):
        key, separator, value = component.strip().partition("=")
        if not separator:
            raise BillingInputError()
        if key == "t":
            timestamps.append(value)
        elif key == "v1" and re.fullmatch(r"[a-fA-F0-9]{64}", value, flags=re.ASCII):
            signatures.append(value.lower())
    if (len(timestamps) != 1 or not signatures
            or not re.fullmatch(r"[0-9]{1,12}", timestamps[0], flags=re.ASCII)):
        raise BillingInputError()
    timestamp = int(timestamps[0])
    if abs((time.time() if now is None else now) - timestamp) > 300:
        raise BillingInputError()
    expected = hmac.new(secret.encode(), timestamps[0].encode() + b"." + body,
                        hashlib.sha256).hexdigest()
    # Evaluate every signature: rotations can include both the old and new digest.
    matches = [hmac.compare_digest(expected, signature) for signature in signatures]
    if not any(matches):
        raise BillingInputError()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BillingInputError()
        result[key] = value
    return result


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BillingInputError()
    return value


def _reject_constant(value: str) -> None:
    del value
    raise BillingInputError()


def _invoice(obj: dict[str, Any]) -> tuple[InvoiceFacts | None, str | None]:
    customer = require_id(obj.get("customer"), "cus")
    amount = require_integer(obj.get("amount_paid"))
    remaining = require_integer(obj.get("amount_remaining"))
    if any(obj.get(name) is not None for name in ("application", "on_behalf_of", "transfer_data")):
        return None, "unsupported_connect_invoice"
    # Ineligible invoices remain observations. They do not reserve an invoice key.
    if (obj.get("status") != "paid" or amount == 0 or remaining != 0
            or obj.get("billing_reason") not in {"subscription_create", "subscription_cycle"}):
        return None, "unsupported_invoice_state"
    currency = obj.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[a-z]{3}", currency, re.ASCII):
        raise BillingInputError()
    for name in ("amount_due", "total", "subtotal"):
        if require_integer(obj.get(name)) != amount:
            return None, "invoice_adjustment"
    for name in ("starting_balance", "ending_balance", "pre_payment_credit_notes_amount",
                 "post_payment_credit_notes_amount"):
        if require_integer(obj.get(name), minimum=-MAX_INTEGER) != 0:
            return None, "invoice_adjustment"
    if obj.get("total_discount_amounts") != [] or obj.get("total_taxes") != []:
        return None, "invoice_adjustment"
    parent = _object(obj.get("parent"))
    if parent.get("type") != "subscription_details":
        return None, "unsupported_invoice_parent"
    subscription = require_id(_object(parent.get("subscription_details")).get("subscription"),
                              "sub")
    lines = _object(obj.get("lines"))
    rows = lines.get("data")
    if lines.get("object") != "list" or lines.get("has_more") is not False:
        return None, "incomplete_invoice_lines"
    if not isinstance(rows, list) or len(rows) != 1:
        return None, "unsupported_invoice_lines"
    if "total_count" in lines and require_integer(lines["total_count"]) != 1:
        return None, "incomplete_invoice_lines"
    line = _object(rows[0])
    if line.get("livemode") is not False or line.get("object") != "line_item":
        raise BillingInputError()
    require_id(line.get("id"), "il")
    if line.get("invoice") is not None and line["invoice"] != obj.get("id"):
        return None, "unsupported_invoice_lines"
    quantity = require_integer(line.get("quantity"), minimum=1)
    line_amount = require_integer(line.get("amount"), minimum=-MAX_INTEGER)
    if quantity != 1 or line_amount != amount or line.get("currency") != currency:
        return None, "unsupported_invoice_lines"
    if line.get("discount_amounts") != [] or line.get("taxes") != []:
        return None, "invoice_adjustment"
    line_parent = _object(line.get("parent"))
    if line_parent.get("type") != "subscription_item_details":
        return None, "unsupported_invoice_lines"
    details = _object(line_parent.get("subscription_item_details"))
    if details.get("proration") is not False or details.get("subscription") != subscription:
        return None, "unsupported_invoice_lines"
    require_id(details.get("subscription_item"), "si")
    pricing = _object(line.get("pricing"))
    if pricing.get("type") != "price_details":
        return None, "unsupported_invoice_lines"
    price_id = require_id(_object(pricing.get("price_details")).get("price"), "price")
    # Exact integer decimal pricing only. Fractional, tiered or metered units need review.
    if pricing.get("unit_amount_decimal") != str(amount):
        return None, "unsupported_invoice_pricing"
    period = _object(line.get("period"))
    start = require_integer(period.get("start"), maximum=MAX_TIMESTAMP)
    end = require_integer(period.get("end"), maximum=MAX_TIMESTAMP)
    if start >= end:
        return None, "unsupported_invoice_period"
    return InvoiceFacts(require_id(obj.get("id"), "in"), customer, subscription, price_id,
                        currency, amount, quantity, start, end, obj["billing_reason"]), None


def parse_event(body: bytes) -> SandboxEvent:
    if len(body) > MAX_BODY_BYTES:
        raise BillingInputError()
    try:
        raw = _object(json.loads(body, object_pairs_hook=_unique_object,
                                 parse_constant=_reject_constant))
        if (raw.get("object") != "event" or raw.get("api_version") != API_VERSION
                or raw.get("livemode") is not False or "account" in raw or "context" in raw):
            raise BillingInputError()
        event_id = require_id(raw.get("id"), "evt")
        event_type = raw.get("type")
        if not isinstance(event_type, str) or not re.fullmatch(r"[a-z_.]{1,100}", event_type):
            raise BillingInputError()
        created = require_integer(raw.get("created"), maximum=MAX_TIMESTAMP)
        obj = _object(_object(raw.get("data")).get("object"))
        object_id = require_id(obj.get("id"))
        if obj.get("livemode") is not False:
            raise BillingInputError()
        customer = require_id(obj["customer"], "cus") if obj.get("customer") else None
        facts: dict[str, Any] = {}
        invoice = None
        review = None
        if event_type == "invoice.paid":
            if obj.get("object") != "invoice":
                raise BillingInputError()
            invoice, review = _invoice(obj)
            if invoice is not None:
                facts = asdict(invoice)
        elif event_type == "invoice.payment_failed":
            if obj.get("object") != "invoice":
                raise BillingInputError()
            require_id(object_id, "in")
            facts = {"status": "payment_failed"}
        elif event_type in {"customer.subscription.created", "customer.subscription.updated",
                            "customer.subscription.deleted"}:
            if obj.get("object") != "subscription":
                raise BillingInputError()
            require_id(object_id, "sub")
            status = obj.get("status")
            if status not in {"incomplete", "incomplete_expired", "trialing", "active", "past_due",
                              "canceled", "unpaid", "paused"}:
                raise BillingInputError()
            facts = {"status": status}
        else:
            review = "unsupported_event_type"
        return SandboxEvent(event_id, event_type, created, object_id, customer,
                            canonical_digest(raw), facts, invoice, review)
    except (ValueError, TypeError, RecursionError, KeyError, OverflowError) as error:
        if isinstance(error, BillingInputError):
            raise
        raise BillingInputError() from None
