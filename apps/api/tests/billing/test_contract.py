"""Synthetic Basil snapshot contracts: no Stripe calls, database or cash payment."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
from pathlib import Path

import pytest

from app.billing.contract import (
    BillingInputError,
    parse_event,
    verify_signature,
)

NOW = 1780000000
SECRET = "whsec_synthetic_contract_only"
FIXTURE = Path(__file__).parent / "fixtures" / "basil_paid.json"


def event() -> dict:
    return json.loads(FIXTURE.read_bytes())


def signed(body: bytes, timestamp: int = NOW) -> str:
    digest = hmac.new(SECRET.encode(), str(timestamp).encode() + b"." + body,
                      hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_signature_uses_exact_raw_bytes_and_rotation_signatures() -> None:
    body = FIXTURE.read_bytes()
    verify_signature(body, signed(body) + ",v1=" + "0" * 64, SECRET, now=NOW)
    with pytest.raises(BillingInputError):
        verify_signature(body + b" ", signed(body), SECRET, now=NOW)


@pytest.mark.parametrize("offset", [-301, 301])
def test_signature_rejects_old_and_future_deliveries(offset: int) -> None:
    body = FIXTURE.read_bytes()
    with pytest.raises(BillingInputError):
        verify_signature(body, signed(body, NOW + offset), SECRET, now=NOW)


@pytest.mark.parametrize("header", ["", "t=1,t=1,v1=" + "0" * 64,
                                    "t=true,v1=" + "0" * 64, "x" * 4097],
                         ids=["empty", "duplicate-timestamp", "invalid-timestamp", "too-long"])
def test_signature_is_bounded_and_rejects_ambiguous_timestamp(header: str) -> None:
    with pytest.raises(BillingInputError):
        verify_signature(b"{}", header, SECRET, now=NOW)


def test_valid_invoice_extracts_only_allowlisted_facts() -> None:
    raw = event()
    raw["data"]["object"]["customer_email"] = "private@example.invalid"
    raw["data"]["object"]["metadata"] = {"owner": "internal-real-budget", "units": 999999}
    parsed = parse_event(json.dumps(raw).encode())
    assert parsed.invoice is not None
    assert parsed.invoice.price_id == "price_synthetic"
    assert parsed.invoice.amount == 1000
    assert parsed.review_reason is None
    assert "private" not in repr(parsed)
    assert "internal-real-budget" not in repr(parsed)


@pytest.mark.parametrize("key,value", [("livemode", True), ("livemode", None),
                                       ("api_version", "2026-09-30.endive"),
                                       ("account", "acct_connected"), ("context", "ctx")])
def test_rejects_live_connect_thin_or_unknown_version(key: str, value: object) -> None:
    raw = event()
    raw[key] = value
    with pytest.raises(BillingInputError):
        parse_event(json.dumps(raw).encode())


def test_duplicate_json_keys_and_body_bounds_rejected() -> None:
    with pytest.raises(BillingInputError):
        parse_event(b'{"livemode":true,"livemode":false}')
    with pytest.raises(BillingInputError):
        parse_event(b" " * (256 * 1024 + 1))


@pytest.mark.parametrize("path,value", [
    (("amount_paid",), True), (("amount_paid",), 2147483648),
    (("lines", "data", 0, "quantity"), True),
    (("lines", "data", 0, "livemode"), None),
])
def test_invalid_money_and_line_mode_rejected(path: tuple, value: object) -> None:
    raw = event()
    obj = raw["data"]["object"]
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value
    with pytest.raises(BillingInputError):
        parse_event(json.dumps(raw).encode())


@pytest.mark.parametrize("path,value", [
    (("lines", "has_more"), True), (("lines", "data", 0, "quantity"), 2),
    (("lines", "data", 0, "parent", "subscription_item_details", "proration"), True),
    (("billing_reason",), "subscription_update"), (("amount_remaining",), 1),
    (("total_discount_amounts",), [{"amount": 100}]),
    (("total_taxes",), [{"amount": 100}]),
    (("starting_balance",), -10), (("post_payment_credit_notes_amount",), 10),
    (("lines", "data", 0, "parent", "subscription_item_details", "subscription"), "sub_other"),
    (("lines", "total_count"), 2),
    (("lines", "data", 0, "invoice"), "in_other"),
    (("application",), "ca_connected"),
    (("on_behalf_of",), "acct_connected"),
    (("transfer_data",), {"destination": "acct_connected"}),
])
def test_unsupported_adjustments_require_review_without_invoice(path: tuple, value: object) -> None:
    raw = copy.deepcopy(event())
    obj = raw["data"]["object"]
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value
    parsed = parse_event(json.dumps(raw).encode())
    assert parsed.invoice is None
    assert parsed.review_reason is not None


def test_lifecycle_events_are_observations_not_ordered_entitlement() -> None:
    raw = event()
    raw["type"] = "customer.subscription.deleted"
    raw["data"]["object"] = {"id": "sub_synthetic", "object": "subscription",
                               "livemode": False, "customer": "cus_synthetic",
                               "status": "canceled"}
    parsed = parse_event(json.dumps(raw).encode())
    assert parsed.invoice is None
    assert parsed.review_reason is None
    assert parsed.facts == {"status": "canceled"}


def test_event_digest_accepts_whitespace_reencoding_but_tracks_changed_facts() -> None:
    raw = event()
    assert parse_event(json.dumps(raw).encode()).digest == parse_event(
        json.dumps(raw, indent=2).encode()).digest
    before = parse_event(json.dumps(raw).encode()).digest
    raw["data"]["object"]["customer"] = "cus_other"
    assert parse_event(json.dumps(raw).encode()).digest != before
