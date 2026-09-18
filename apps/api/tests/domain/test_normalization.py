from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models import RawRecord
from app.services.normalize import normalize_raw_record


@pytest.fixture
def source_id():  # type: ignore[no-untyped-def]
    return uuid4()


@pytest.fixture(
    params=[
        ("pre-specification", "Synthetic cloud migration pre-specification"),
        ("tender", "Synthetic cloud migration tender"),
        ("amendment", "Synthetic cloud migration amendment"),
        ("award", "Synthetic cloud migration award"),
        ("contract", "Synthetic cloud migration contract"),
    ]
)
def lifecycle_raw_record(request: pytest.FixtureRequest, source_id) -> RawRecord:  # type: ignore[no-untyped-def]
    stage, title = request.param
    return RawRecord(
        source_id=source_id,
        source_record_id=f"synthetic-{stage}-001",
        source_updated_at=datetime(2026, 9, 10, 9, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 9, 11, 9, 0, tzinfo=UTC),
        payload_json={
            "title": title,
            "buyer_name": "Synthetic Seoul Digital Agency",
            "procurement_type": "services",
            "lifecycle_stage": stage,
            "estimated_amount": "125000000.00",
            "currency": "KRW",
            "published_at": "2026-09-09T00:00:00+00:00",
            "closes_at": "2026-09-30T09:00:00+00:00",
            "status": "published",
            "is_synthetic": True,
        },
        payload_sha256="a" * 64,
    )


def test_normalizes_all_supported_lifecycle_fixtures(
    lifecycle_raw_record: RawRecord,
) -> None:
    normalized = normalize_raw_record(lifecycle_raw_record)

    assert normalized.source_id == lifecycle_raw_record.source_id
    assert normalized.source_record_id == lifecycle_raw_record.source_record_id
    expected_digest = hashlib.sha256(lifecycle_raw_record.source_record_id.encode()).hexdigest()
    assert normalized.canonical_key == f"{lifecycle_raw_record.source_id}:{expected_digest}"
    assert normalized.lifecycle_stage == lifecycle_raw_record.payload_json["lifecycle_stage"]
    assert normalized.estimated_amount == Decimal("125000000.00")
    assert normalized.effective_at == lifecycle_raw_record.source_updated_at
    assert normalized.normalized_json["is_synthetic"] is True


def test_normalized_checksum_ignores_raw_transport_and_fetch_metadata(source_id) -> None:  # type: ignore[no-untyped-def]
    payload = {
        "title": "Synthetic tender",
        "buyer_name": "Synthetic buyer",
        "lifecycle_stage": "tender",
    }
    first = RawRecord(
        source_id=source_id,
        source_record_id="immutable-upstream-id",
        fetched_at=datetime(2026, 9, 10, tzinfo=UTC),
        payload_json=payload,
        payload_sha256="a" * 64,
        http_etag='"v1"',
    )
    second = RawRecord(
        source_id=source_id,
        source_record_id="immutable-upstream-id",
        fetched_at=datetime(2026, 9, 11, tzinfo=UTC),
        payload_json=payload,
        payload_sha256="b" * 64,
        http_etag='"v2"',
    )

    assert (
        normalize_raw_record(first).normalized_sha256
        == normalize_raw_record(second).normalized_sha256
    )


def test_missing_required_business_field_is_rejected(source_id) -> None:  # type: ignore[no-untyped-def]
    raw = RawRecord(
        source_id=source_id,
        source_record_id="missing-title",
        payload_json={"buyer_name": "Synthetic buyer", "lifecycle_stage": "tender"},
        payload_sha256="a" * 64,
    )

    with pytest.raises(ValueError, match="title"):
        normalize_raw_record(raw)


def test_null_required_business_field_is_rejected(source_id) -> None:  # type: ignore[no-untyped-def]
    raw = RawRecord(
        source_id=source_id,
        source_record_id="null-title",
        payload_json={"title": None, "buyer_name": "Synthetic buyer", "lifecycle_stage": "tender"},
        payload_sha256="a" * 64,
    )

    with pytest.raises(ValueError, match="title"):
        normalize_raw_record(raw)


def test_canonical_key_is_bounded_for_maximum_length_upstream_id(source_id) -> None:  # type: ignore[no-untyped-def]
    raw = RawRecord(
        source_id=source_id,
        source_record_id="x" * 255,
        fetched_at=datetime(2026, 9, 10, tzinfo=UTC),
        payload_json={
            "title": "Synthetic",
            "buyer_name": "Synthetic buyer",
            "lifecycle_stage": "tender",
        },
        payload_sha256="a" * 64,
    )

    normalized = normalize_raw_record(raw)

    assert len(normalized.canonical_key) == 101
    assert normalized.source_record_id == "x" * 255


def test_semantically_equivalent_values_have_the_same_checksum(source_id) -> None:  # type: ignore[no-untyped-def]
    common = {"title": "Synthetic", "buyer_name": "Synthetic buyer", "lifecycle_stage": "tender"}
    first = RawRecord(
        source_id=source_id,
        source_record_id="same",
        payload_json={
            **common,
            "estimated_amount": "100",
            "published_at": "2026-09-10T09:00:00+09:00",
            "regions": ["Seoul", "Busan"],
        },
        payload_sha256="a" * 64,
    )
    second = RawRecord(
        source_id=source_id,
        source_record_id="same",
        payload_json={
            **common,
            "estimated_amount": "100.00",
            "published_at": "2026-09-10T00:00:00+00:00",
            "regions": ["Busan", "Seoul"],
        },
        payload_sha256="b" * 64,
    )

    assert (
        normalize_raw_record(first).normalized_sha256
        == normalize_raw_record(second).normalized_sha256
    )
