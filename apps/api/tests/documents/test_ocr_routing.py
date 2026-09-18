from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.download import StoredAttachment
from app.documents.ocr import (
    FakeFixtureOcrAdapter,
    OcrDocument,
    OcrResult,
    should_use_ocr,
)
from app.documents.parsers import ParsedDocument, ParsedPage, parse_document
from app.documents.quality import assess_text_quality
from app.documents.service import persist_and_parse_attachments
from app.documents.synthetic_fixtures import (
    SYNTHETIC_SCANNED_GROUND_TRUTH,
    load_packaged_fixture,
)
from app.models import (
    Attachment,
    DocumentParse,
    JobFailure,
    Opportunity,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
)
from app.sources.base import AttachmentRef
from app.workers.jobs import reconcile_pending_documents


def _parsed(*pages: str, status: str = "parsed") -> ParsedDocument:
    parsed_pages = tuple(ParsedPage(index, text) for index, text in enumerate(pages, 1))
    text = "\n\n".join(pages)
    return ParsedDocument(
        checksum="a" * 64,
        parser_kind="native_pdf",
        parser_version="native-v1",
        pages=parsed_pages,
        page_count=len(parsed_pages),
        extracted_text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        status=status,
    )


def _stored(content: bytes, filename: str = "document.pdf") -> StoredAttachment:
    checksum = hashlib.sha256(content).hexdigest()
    return StoredAttachment(
        sha256=checksum,
        byte_size=len(content),
        media_type="application/pdf",
        filename=filename,
        storage_key=f"sha256/{checksum[:2]}/{checksum}.blob",
        original_bytes=content,
    )


def test_quality_gate_skips_trusted_native_and_routes_low_quality_pdf() -> None:
    trusted = assess_text_quality(
        _parsed("Substantial native procurement notice text with reliable evidence.")
    )
    empty = assess_text_quality(_parsed(""))
    garbled = assess_text_quality(_parsed("!@#$%^&*()"))
    mixed = assess_text_quality(
        _parsed("Substantial native procurement notice text with reliable evidence.", "")
    )
    unsupported = assess_text_quality(_parsed("", status="unsupported"))

    assert should_use_ocr(trusted) is False
    assert should_use_ocr(empty) is True
    assert should_use_ocr(garbled) is True
    assert should_use_ocr(mixed) is True
    assert should_use_ocr(unsupported) is False


@pytest.mark.asyncio
async def test_fake_ocr_is_fixture_scoped_and_unknown_content_gets_no_ground_truth() -> None:
    adapter = FakeFixtureOcrAdapter()
    fixture_bytes = load_packaged_fixture("synthetic-scanned-specification.pdf")
    native = parse_document(_stored(fixture_bytes, "synthetic-scanned-specification.pdf"))

    recognized = await adapter.recognize(
        OcrDocument(
            attachment=_stored(fixture_bytes, "synthetic-scanned-specification.pdf"),
            native_parse=native,
            fixture_key="synthetic-scanned-specification.pdf",
        )
    )
    unknown = await adapter.recognize(
        OcrDocument(
            attachment=_stored(fixture_bytes + b"unknown"),
            native_parse=native,
            fixture_key=None,
        )
    )

    assert isinstance(recognized, OcrResult)
    assert recognized.provider == "synthetic_fixture_fake"
    assert recognized.synthetic is True
    assert recognized.status == "recognized"
    assert tuple(page.text for page in recognized.pages) == SYNTHETIC_SCANNED_GROUND_TRUTH
    assert unknown.status == "unavailable"
    assert unknown.pages == ()
    assert unknown.extracted_text == ""


def test_scanned_fixture_has_stable_bytes_and_no_native_text() -> None:
    content = load_packaged_fixture("synthetic-scanned-specification.pdf")

    assert hashlib.sha256(content).hexdigest() == (
        "ab7478c072659a1c3dba423fc56a26aaa4e66b7531ce0125f12ef059fa96c62d"
    )
    native = parse_document(_stored(content, "synthetic-scanned-specification.pdf"))
    assert native.page_count == 2
    assert all(page.text.strip() == "" for page in native.pages)
    assert should_use_ocr(assess_text_quality(native)) is True


@pytest.mark.asyncio
async def test_pipeline_persists_native_and_ocr_rows_and_replay_is_idempotent(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SourceRegistry(
        code="ocr-test", display_name="Synthetic OCR test", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    raw = RawRecord(
        source_id=source.id,
        source_record_id="scanned",
        payload_json={"is_synthetic": True},
        payload_sha256="a" * 64,
    )
    opportunity = Opportunity(
        canonical_key="ocr-test:scanned", title="Synthetic scan", buyer_name="Synthetic Buyer"
    )
    session.add_all([raw, opportunity])
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=opportunity.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id=raw.source_record_id,
        normalized_json={},
        normalized_sha256="b" * 64,
    )
    session.add(version)
    await session.flush()
    ref = AttachmentRef(
        attachment_id="synthetic-scan",
        filename="synthetic-scanned-specification.pdf",
        url="https://example.invalid/synthetic-scanned-specification.pdf",
        media_type="application/pdf",
        fixture_key="synthetic-scanned-specification.pdf",
    )

    await persist_and_parse_attachments(
        session,
        opportunity_version_id=version.id,
        refs=[ref],
        allowed_source_host="example.invalid",
        storage_root=tmp_path,
    )
    await session.flush()

    attachment = await session.scalar(
        select(Attachment).where(Attachment.opportunity_version_id == version.id)
    )
    recovered_ocr = await session.scalar(
        select(DocumentParse).where(
            DocumentParse.attachment_id == attachment.id,
            DocumentParse.parser_kind == "ocr",
        )
    )
    legacy_row_id = recovered_ocr.id
    recovered_ocr.parser_version = "ocr-fixture-fake-v1"
    await session.flush()

    class CountingFake(FakeFixtureOcrAdapter):
        calls = 0

        async def recognize(self, document: OcrDocument) -> OcrResult:
            self.calls += 1
            return await super().recognize(document)

    counting_fake = CountingFake()
    legacy_replay_processed = await persist_and_parse_attachments(
        session,
        opportunity_version_id=version.id,
        refs=[ref],
        allowed_source_host="example.invalid",
        storage_root=tmp_path,
        ocr_adapter=counting_fake,
    )
    await session.flush()
    assert counting_fake.calls == 0
    assert legacy_replay_processed == 0
    assert recovered_ocr.id == legacy_row_id
    assert recovered_ocr.parser_version != "ocr-fixture-fake-v1"

    ocr_row = await session.scalar(
        select(DocumentParse).where(
            DocumentParse.attachment_id == attachment.id,
            DocumentParse.parser_kind == "ocr",
        )
    )
    await session.delete(ocr_row)
    await session.flush()

    async def reject_redownload(*args: object, **kwargs: object) -> StoredAttachment:
        del args, kwargs
        raise AssertionError("persisted native OCR recovery must reuse the checksum blob")

    monkeypatch.setattr("app.documents.service.download_attachment", reject_redownload)
    await persist_and_parse_attachments(
        session,
        opportunity_version_id=version.id,
        refs=[ref],
        allowed_source_host="example.invalid",
        storage_root=tmp_path,
    )
    await session.flush()

    parses = (
        await session.scalars(
            select(DocumentParse)
            .where(DocumentParse.attachment_id == attachment.id)
            .order_by(DocumentParse.parser_kind)
        )
    ).all()

    assert [parse.parser_kind for parse in parses] == ["native_pdf", "ocr"]
    native, ocr = parses
    assert native.status == "needs_ocr"
    assert native.extracted_text == "\n\n"
    assert ocr.status == "trusted"
    assert ocr.quality_json["provider"] == "synthetic_fixture_fake"
    assert ocr.quality_json["synthetic"] is True
    assert [page["page_number"] for page in ocr.quality_json["pages"]] == [1, 2]
    assert ocr.extracted_text == "\n\n".join(SYNTHETIC_SCANNED_GROUND_TRUTH)


@pytest.mark.asyncio
async def test_trusted_native_parse_does_not_call_ocr(
    session: AsyncSession, tmp_path: Path
) -> None:
    class RejectingOcr:
        provider = "rejecting"
        provider_version = "v1"

        async def recognize(self, document: OcrDocument) -> OcrResult:
            del document
            raise AssertionError("OCR must not run for trusted native text")

    source = SourceRegistry(
        code="ocr-skip", display_name="OCR skip", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    raw = RawRecord(
        source_id=source.id,
        source_record_id="native",
        payload_json={},
        payload_sha256="c" * 64,
    )
    opportunity = Opportunity(
        canonical_key="ocr-skip:native", title="Native", buyer_name="Buyer"
    )
    session.add_all([raw, opportunity])
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=opportunity.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id=raw.source_record_id,
        normalized_json={},
        normalized_sha256="d" * 64,
    )
    session.add(version)
    await session.flush()

    await persist_and_parse_attachments(
        session,
        opportunity_version_id=version.id,
        refs=[
            AttachmentRef(
                attachment_id="native",
                filename="synthetic-specification.html",
                url="https://example.invalid/synthetic-specification.html",
                media_type="text/html",
                fixture_key="synthetic-specification.html",
            )
        ],
        allowed_source_host="example.invalid",
        storage_root=tmp_path,
        ocr_adapter=RejectingOcr(),
    )
    await session.flush()

    attachment = await session.scalar(
        select(Attachment).where(Attachment.opportunity_version_id == version.id)
    )
    kinds = (
        await session.scalars(
            select(DocumentParse.parser_kind).where(DocumentParse.attachment_id == attachment.id)
        )
    ).all()
    assert kinds == ["html"]


@pytest.mark.asyncio
async def test_worker_retries_ocr_without_losing_native_parse(
    session: AsyncSession, tmp_path: Path
) -> None:
    class FailingOcr:
        provider = "failing"
        provider_version = "v1"

        async def recognize(self, document: OcrDocument) -> OcrResult:
            del document
            raise httpx.ConnectError("synthetic OCR provider unavailable")

    source = SourceRegistry(
        code="mock", display_name="Synthetic mock OCR retry", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    raw = RawRecord(
        source_id=source.id,
        source_record_id="synthetic-pre-spec-001",
        payload_json={"title": "Synthetic", "is_synthetic": True},
        payload_sha256="e" * 64,
        normalization_status="normalized",
    )
    opportunity = Opportunity(
        canonical_key="mock:ocr-retry", title="Synthetic", buyer_name="Synthetic Buyer"
    )
    session.add_all([raw, opportunity])
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=opportunity.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id=raw.source_record_id,
        normalized_json={},
        normalized_sha256="f" * 64,
    )
    session.add(version)
    await session.flush()

    ctx = {
        "session": session,
        "attachment_storage_path": tmp_path,
        "ocr_adapter": FailingOcr(),
    }
    assert await reconcile_pending_documents(ctx) == {"processed": 0, "failed": 1}

    attachments = (
        await session.scalars(
            select(Attachment).where(Attachment.opportunity_version_id == version.id)
        )
    ).all()
    native_rows = (
        await session.scalars(
            select(DocumentParse).where(
                DocumentParse.attachment_id.in_([item.id for item in attachments]),
                DocumentParse.parser_kind == "native_pdf",
            )
        )
    ).all()
    failure = await session.scalar(
        select(JobFailure).where(JobFailure.job_type == "parse_documents")
    )
    assert len(native_rows) == 2
    assert failure.attempts == 1
    assert failure.dead_lettered is False

    failure.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    ctx["ocr_adapter"] = FakeFixtureOcrAdapter()
    assert await reconcile_pending_documents(ctx) == {"processed": 1, "failed": 0}

    ocr_rows = (
        await session.scalars(
            select(DocumentParse).where(
                DocumentParse.attachment_id.in_([item.id for item in attachments]),
                DocumentParse.parser_kind == "ocr",
            )
        )
    ).all()
    await session.refresh(failure)
    assert len(ocr_rows) == 1
    assert failure.attempts == 0
    assert failure.dead_lettered is False


@pytest.mark.asyncio
async def test_same_local_version_from_two_providers_preserves_both_ocr_rows(
    session: AsyncSession, tmp_path: Path
) -> None:
    class ProviderOcr:
        provider_version = "v1"

        def __init__(self, provider: str) -> None:
            self.provider = provider

        async def recognize(self, document: OcrDocument) -> OcrResult:
            del document
            text = f"Synthetic result from {self.provider} with enough trusted text."
            return OcrResult(
                provider=self.provider,
                provider_version=self.provider_version,
                synthetic=True,
                pages=(ParsedPage(1, text),),
                extracted_text=text,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                status="recognized",
            )

    source = SourceRegistry(
        code="ocr-providers", display_name="OCR providers", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    raw = RawRecord(
        source_id=source.id,
        source_record_id="providers",
        payload_json={},
        payload_sha256="1" * 64,
    )
    opportunity = Opportunity(
        canonical_key="ocr-providers:notice", title="Providers", buyer_name="Buyer"
    )
    session.add_all([raw, opportunity])
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=opportunity.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id=raw.source_record_id,
        normalized_json={},
        normalized_sha256="2" * 64,
    )
    session.add(version)
    await session.flush()
    ref = AttachmentRef(
        attachment_id="provider-scan",
        filename="synthetic-scanned-specification.pdf",
        url="https://example.invalid/provider-scan.pdf",
        media_type="application/pdf",
        fixture_key="synthetic-scanned-specification.pdf",
    )

    for provider in ("vendor_a", "vendor_b", "vendor_a", "vendor_b"):
        await persist_and_parse_attachments(
            session,
            opportunity_version_id=version.id,
            refs=[ref],
            allowed_source_host="example.invalid",
            storage_root=tmp_path,
            ocr_adapter=ProviderOcr(provider),
        )

    attachment = await session.scalar(
        select(Attachment).where(Attachment.opportunity_version_id == version.id)
    )
    rows = (
        await session.scalars(
            select(DocumentParse)
            .where(DocumentParse.attachment_id == attachment.id)
            .order_by(DocumentParse.parser_kind, DocumentParse.parser_version)
        )
    ).all()
    assert [row.parser_kind for row in rows] == ["native_pdf", "ocr", "ocr"]
    assert {row.quality_json["provider"] for row in rows if row.parser_kind == "ocr"} == {
        "vendor_a",
        "vendor_b",
    }
    assert len({row.parser_version for row in rows if row.parser_kind == "ocr"}) == 2


@pytest.mark.asyncio
async def test_garbled_native_pdf_invokes_ocr_adapter_and_keeps_native_row(
    session: AsyncSession, tmp_path: Path
) -> None:
    calls = 0

    class SpyOcr:
        provider = "spy"
        provider_version = "v1"

        async def recognize(self, document: OcrDocument) -> OcrResult:
            nonlocal calls
            calls += 1
            assert "!@#$" in document.native_parse.extracted_text
            text = "!@#$%^&*()"
            return OcrResult(
                provider=self.provider,
                provider_version=self.provider_version,
                synthetic=True,
                pages=(ParsedPage(1, text),),
                extracted_text=text,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                status="recognized",
            )

    source = SourceRegistry(
        code="ocr-garbled", display_name="OCR garbled", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    raw = RawRecord(
        source_id=source.id,
        source_record_id="garbled",
        payload_json={},
        payload_sha256="3" * 64,
    )
    opportunity = Opportunity(
        canonical_key="ocr-garbled:notice", title="Garbled", buyer_name="Buyer"
    )
    session.add_all([raw, opportunity])
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=opportunity.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id=raw.source_record_id,
        normalized_json={},
        normalized_sha256="4" * 64,
    )
    session.add(version)
    await session.flush()
    ref = AttachmentRef(
        attachment_id="garbled",
        filename="synthetic-garbled.pdf",
        url="https://example.invalid/synthetic-garbled.pdf",
        media_type="application/pdf",
        fixture_key="synthetic-garbled.pdf",
    )

    first_processed = await persist_and_parse_attachments(
        session,
        opportunity_version_id=version.id,
        refs=[ref],
        allowed_source_host="example.invalid",
        storage_root=tmp_path,
        ocr_adapter=SpyOcr(),
    )
    repeated_processed = await persist_and_parse_attachments(
        session,
        opportunity_version_id=version.id,
        refs=[ref],
        allowed_source_host="example.invalid",
        storage_root=tmp_path,
        ocr_adapter=SpyOcr(),
    )

    attachment = await session.scalar(
        select(Attachment).where(Attachment.opportunity_version_id == version.id)
    )
    rows = (
        await session.scalars(
            select(DocumentParse).where(DocumentParse.attachment_id == attachment.id)
        )
    ).all()
    assert calls == 1
    assert first_processed == 1
    assert repeated_processed == 0
    assert {row.parser_kind for row in rows} == {"native_pdf", "ocr"}
    native = next(row for row in rows if row.parser_kind == "native_pdf")
    ocr = next(row for row in rows if row.parser_kind == "ocr")
    assert native.status == "needs_ocr"
    assert "!@#$" in native.extracted_text
    assert ocr.status == "needs_ocr"
    assert ocr.quality_json["recognition_status"] == "recognized"
