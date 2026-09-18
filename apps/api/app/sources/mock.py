from __future__ import annotations

from app.sources.base import AttachmentRef, DiscoveryPage, RawSourceRecord


class MockSourceAdapter:
    """Deterministic synthetic source for local development and CI."""

    _RECORDS = (
        RawSourceRecord(
            source_record_id="synthetic-pre-spec-001",
            raw_payload={
                "title": "Synthetic cloud migration pre-specification",
                "buyer_name": "Synthetic Seoul Digital Agency",
                "procurement_type": "services",
                "lifecycle_stage": "pre-specification",
                "published_at": "2026-09-01T00:00:00+00:00",
                "is_synthetic": True,
                "nested": {"mutable": "original"},
            },
            source_url="https://example.invalid/synthetic-pre-spec-001",
        ),
        RawSourceRecord(
            source_record_id="synthetic-tender-001",
            raw_payload={
                "title": "Synthetic cloud migration tender",
                "buyer_name": "Synthetic Seoul Digital Agency",
                "procurement_type": "services",
                "lifecycle_stage": "tender",
                "estimated_amount": "125000000",
                "published_at": "2026-09-03T00:00:00+00:00",
                "closes_at": "2026-09-30T09:00:00+00:00",
                "official_references": [
                    {
                        "source_record_id": "synthetic-pre-spec-001",
                        "lifecycle_stage": "pre-specification",
                    }
                ],
                "is_synthetic": True,
            },
            source_url="https://example.invalid/synthetic-tender-001",
        ),
        RawSourceRecord(
            source_record_id="synthetic-amendment-001",
            raw_payload={
                "title": "Synthetic cloud migration amendment",
                "buyer_name": "Synthetic Seoul Digital Agency",
                "lifecycle_stage": "amendment",
                "closes_at": "2026-10-02T09:00:00+00:00",
                "estimated_amount": "125000000",
                "currency": "KRW",
                "regions": [],
                "required_certifications": [],
                "revision": 1,
                "official_references": [
                    {
                        "source_record_id": "synthetic-tender-001",
                        "lifecycle_stage": "tender",
                    }
                ],
                "is_synthetic": True,
            },
            source_url="https://example.invalid/synthetic-amendment-001",
        ),
        RawSourceRecord(
            source_record_id="synthetic-amendment-001",
            raw_payload={
                "title": "Synthetic cloud migration amendment (corrected)",
                "description": (
                    "Synthetic information technology cloud migration and document processing"
                ),
                "buyer_name": "Synthetic Seoul Digital Agency",
                "procurement_type": "information-technology",
                "lifecycle_stage": "amendment",
                "closes_at": "2026-10-05T09:00:00+00:00",
                "estimated_amount": "150000000",
                "currency": "KRW",
                "regions": ["Seoul"],
                "required_certifications": ["ISO 27001"],
                "required_capabilities": ["cloud migration", "document processing"],
                "revision": 2,
                "official_references": [
                    {
                        "source_record_id": "synthetic-tender-001",
                        "lifecycle_stage": "tender",
                    }
                ],
                "is_synthetic": True,
            },
            source_url="https://example.invalid/synthetic-amendment-001",
        ),
        RawSourceRecord(
            source_record_id="synthetic-award-001",
            raw_payload={
                "title": "Synthetic cloud migration award",
                "buyer_name": "Synthetic Seoul Digital Agency",
                "lifecycle_stage": "award",
                "official_references": [
                    {
                        "source_record_id": "synthetic-amendment-001",
                        "lifecycle_stage": "amendment",
                    }
                ],
                "is_synthetic": True,
            },
            source_url="https://example.invalid/synthetic-award-001",
        ),
        RawSourceRecord(
            source_record_id="synthetic-contract-001",
            raw_payload={
                "title": "Synthetic cloud migration contract",
                "buyer_name": "Synthetic Seoul Digital Agency",
                "lifecycle_stage": "contract",
                "contract_period": "2026-10-15/2027-04-14",
                "official_references": [
                    {
                        "source_record_id": "synthetic-award-001",
                        "lifecycle_stage": "award",
                    }
                ],
                "is_synthetic": True,
            },
            source_url="https://example.invalid/synthetic-contract-001",
        ),
    )

    def __init__(self, page_size: int = 2) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least one")
        self._page_size = page_size

    async def discover(self, cursor: str | None) -> DiscoveryPage:
        start = int(cursor) if cursor is not None else 0
        if start < 0:
            raise ValueError("cursor cannot be negative")
        records = self._RECORDS[start : start + self._page_size]
        next_index = start + len(records)
        next_cursor = str(next_index) if next_index < len(self._RECORDS) else None
        return DiscoveryPage(
            records=tuple(record.model_copy(deep=True) for record in records),
            next_cursor=next_cursor,
        )

    async def fetch_record(self, source_record_id: str) -> RawSourceRecord:
        for record in self._RECORDS:
            if record.source_record_id == source_record_id:
                return record.model_copy(deep=True)
        raise KeyError(f"unknown synthetic source record: {source_record_id}")

    async def fetch_attachments(self, record: RawSourceRecord) -> list[AttachmentRef]:
        is_pdf = record.source_record_id == "synthetic-pre-spec-001"
        attachments = [
            AttachmentRef(
                attachment_id=f"{record.source_record_id}-specification",
                filename="synthetic-specification.pdf"
                if is_pdf
                else "synthetic-specification.html",
                url=(
                    f"https://example.invalid/{record.source_record_id}/specification.pdf"
                    if is_pdf
                    else f"https://example.invalid/{record.source_record_id}/specification.html"
                ),
                media_type="application/pdf" if is_pdf else "text/html",
                fixture_key=(
                    "synthetic-specification.pdf" if is_pdf else "synthetic-specification.html"
                ),
            )
        ]
        if is_pdf:
            attachments.append(
                AttachmentRef(
                    attachment_id=f"{record.source_record_id}-scanned-specification",
                    filename="synthetic-scanned-specification.pdf",
                    url=(
                        f"https://example.invalid/{record.source_record_id}/"
                        "scanned-specification.pdf"
                    ),
                    media_type="application/pdf",
                    fixture_key="synthetic-scanned-specification.pdf",
                )
            )
        if record.source_record_id == "synthetic-tender-001":
            attachments.append(
                AttachmentRef(
                    attachment_id="synthetic-tender-001-details-v2",
                    filename="synthetic-tender-details-v2.html",
                    url="https://example.invalid/synthetic-tender-001/details-v2.html",
                    media_type="text/html",
                    fixture_key="synthetic-tender-details-v2.html",
                )
            )
        return attachments
