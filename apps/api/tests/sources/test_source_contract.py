import pytest
from pydantic import ValidationError

from app.sources.base import AttachmentRef, DiscoveryPage, RawSourceRecord, SourceAdapter
from app.sources.mock import MockSourceAdapter


def test_source_dtos_are_immutable() -> None:
    record = RawSourceRecord(
        source_record_id="notice-001", raw_payload={"title": "Synthetic notice"}
    )

    with pytest.raises(ValidationError):
        record.source_record_id = "changed"  # type: ignore[misc]


def test_raw_source_record_preserves_optional_transport_metadata() -> None:
    record = RawSourceRecord(
        source_record_id="notice-1",
        raw_payload={"title": "Synthetic"},
        http_etag='"v1"',
        http_last_modified="Wed, 16 Sep 2026 00:00:00 GMT",
    )

    assert record.http_etag == '"v1"'
    assert record.http_last_modified == "Wed, 16 Sep 2026 00:00:00 GMT"


@pytest.mark.asyncio
async def test_mock_source_has_deterministic_pagination_and_logical_lifecycle() -> None:
    adapter: SourceAdapter = MockSourceAdapter(page_size=1)

    first_page = await adapter.discover(None)
    second_page = await adapter.discover(first_page.next_cursor)

    assert isinstance(first_page, DiscoveryPage)
    assert [record.source_record_id for record in first_page.records] == ["synthetic-pre-spec-001"]
    assert [record.source_record_id for record in second_page.records] == ["synthetic-tender-001"]
    assert first_page.records[0].raw_payload["lifecycle_stage"] == "pre-specification"
    assert second_page.records[0].raw_payload["lifecycle_stage"] == "tender"


@pytest.mark.asyncio
async def test_mock_source_rejects_negative_cursor() -> None:
    adapter = MockSourceAdapter()

    with pytest.raises(ValueError, match="cursor cannot be negative"):
        await adapter.discover("-1")


@pytest.mark.asyncio
async def test_mock_source_fetches_raw_record_and_attachment_references() -> None:
    adapter = MockSourceAdapter()

    record = await adapter.fetch_record("synthetic-pre-spec-001")
    attachments = await adapter.fetch_attachments(record)

    assert record.raw_payload == {
        "title": "Synthetic cloud migration pre-specification",
        "buyer_name": "Synthetic Seoul Digital Agency",
        "procurement_type": "services",
        "lifecycle_stage": "pre-specification",
        "published_at": "2026-09-01T00:00:00+00:00",
        "is_synthetic": True,
        "nested": {"mutable": "original"},
    }
    assert attachments == [
        AttachmentRef(
            attachment_id="synthetic-pre-spec-001-specification",
            filename="synthetic-specification.pdf",
            url="https://example.invalid/synthetic-pre-spec-001/specification.pdf",
            media_type="application/pdf",
            fixture_key="synthetic-specification.pdf",
        ),
        AttachmentRef(
            attachment_id="synthetic-pre-spec-001-scanned-specification",
            filename="synthetic-scanned-specification.pdf",
            url="https://example.invalid/synthetic-pre-spec-001/scanned-specification.pdf",
            media_type="application/pdf",
            fixture_key="synthetic-scanned-specification.pdf",
        )
    ]


@pytest.mark.asyncio
async def test_mock_source_returns_defensive_raw_payload_copies() -> None:
    adapter = MockSourceAdapter()
    first = await adapter.fetch_record("synthetic-pre-spec-001")
    first.raw_payload["nested"]["mutable"] = "changed"  # type: ignore[index]

    second = await adapter.fetch_record("synthetic-pre-spec-001")

    assert second.raw_payload["nested"] == {"mutable": "original"}
