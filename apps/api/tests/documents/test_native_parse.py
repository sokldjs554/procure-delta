from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.download import (
    AttachmentDownloadRef,
    StoredAttachment,
    UnsafeAttachmentURLError,
    download_attachment,
)
from app.documents.parsers import ParsedDocument, ParsedPage, parse_document
from app.documents.quality import assess_text_quality
from app.documents.service import persist_and_parse_attachments
from app.documents.synthetic_fixtures import load_packaged_fixture
from app.models import (
    Attachment,
    DocumentParse,
    Opportunity,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
)
from app.sources.base import AttachmentRef
from app.workers.jobs import reconcile_pending_documents


def _pdf_bytes(*pages: str) -> bytes:
    import pymupdf

    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


@pytest.fixture(autouse=True)
def public_attachment_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(_hostname: str) -> tuple[str, ...]:
        return ("93.184.216.34",)

    monkeypatch.setattr("app.documents.download._resolve_public_addresses", resolve)


def test_packaged_pdf_has_restart_stable_checksum() -> None:
    content = load_packaged_fixture("synthetic-specification.pdf")
    assert hashlib.sha256(content).hexdigest() == (
        "e018e88eaf05d34b2ecae022945b69e3e077e44c0f3e299061340ffbf39c500c"
    )


def test_quality_routes_mixed_good_and_empty_pages_to_ocr() -> None:
    parsed = ParsedDocument(
        checksum="a" * 64,
        parser_kind="native_pdf",
        parser_version="native-v1",
        pages=(
            ParsedPage(1, "This page contains substantial native procurement evidence text."),
            ParsedPage(2, ""),
            ParsedPage(3, "!@#$%^&*()"),
        ),
        page_count=3,
        extracted_text=(
            "This page contains substantial native procurement evidence text.\n\n\n\n!@#$%^&*()"
        ),
        text_sha256="b" * 64,
        status="parsed",
    )

    quality = assess_text_quality(parsed)

    assert quality.status == "needs_ocr"
    assert quality.page_signals[0].status == "trusted"
    assert quality.page_signals[1].reasons == ("empty_text",)
    assert "low_alphanumeric_ratio" in quality.page_signals[2].reasons


@pytest.mark.asyncio
async def test_download_pins_validated_ip_and_preserves_tls_hostname(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolutions = 0

    async def resolve(_hostname: str) -> tuple[str, ...]:
        nonlocal resolutions
        resolutions += 1
        return ("93.184.216.34",) if resolutions == 1 else ("127.0.0.1",)

    monkeypatch.setattr("app.documents.download._resolve_public_addresses", resolve)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "files.example.test"
        assert request.extensions["sni_hostname"] == b"files.example.test"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<p>Validated connection target</p>",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await download_attachment(
            AttachmentDownloadRef(
                source_url="https://files.example.test/a.html",
                filename="a.html",
                declared_media_type="text/html",
                allowed_source_host="files.example.test",
            ),
            client=client,
            storage_root=tmp_path,
        )
    assert resolutions == 1


@pytest.mark.asyncio
async def test_download_deduplicates_identical_bytes_by_checksum(tmp_path: Path) -> None:
    content = _pdf_bytes("Synthetic procurement notice")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf", "content-length": str(len(content))},
            content=content,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await download_attachment(
            AttachmentDownloadRef(
                source_url="https://files.example.test/a.pdf",
                filename="../../unsafe a.pdf",
                declared_media_type="application/pdf",
                allowed_source_host="files.example.test",
            ),
            client=client,
            storage_root=tmp_path,
        )
        second = await download_attachment(
            AttachmentDownloadRef(
                source_url="https://files.example.test/renamed.pdf",
                filename="renamed.pdf",
                declared_media_type="application/pdf",
                allowed_source_host="files.example.test",
            ),
            client=client,
            storage_root=tmp_path,
        )

    assert first.sha256 == hashlib.sha256(content).hexdigest() == second.sha256
    assert first.storage_key == second.storage_key
    assert first.original_bytes == content == second.original_bytes
    assert first.filename == "unsafe_a.pdf"
    assert len(list(tmp_path.rglob("*.blob"))) == 1


@pytest.mark.asyncio
async def test_download_rejects_private_hosts_credentials_redirects_and_oversize(
    tmp_path: Path,
) -> None:
    with pytest.raises(UnsafeAttachmentURLError):
        await download_attachment(
            AttachmentDownloadRef(
                source_url="http://user:secret@127.0.0.1/file.pdf",
                filename="file.pdf",
                declared_media_type="application/pdf",
                allowed_source_host="127.0.0.1",
            ),
            storage_root=tmp_path,
        )

    async def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"location": "http://127.0.0.1/private"}, request=request
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(UnsafeAttachmentURLError):
            await download_attachment(
                AttachmentDownloadRef(
                    source_url="https://files.example.test/a.pdf",
                    filename="a.pdf",
                    declared_media_type="application/pdf",
                    allowed_source_host="files.example.test",
                ),
                client=client,
                storage_root=tmp_path,
            )


@pytest.mark.asyncio
async def test_download_retries_server_errors_but_not_client_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("app.documents.download.asyncio.sleep", no_sleep)

    async def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<p>Synthetic recovered attachment text</p>",
            request=request,
        )

    ref = AttachmentDownloadRef(
        source_url="https://files.example.test/a.html",
        filename="a.html",
        declared_media_type="text/html",
        allowed_source_host="files.example.test",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(flaky)) as client:
        stored = await download_attachment(ref, client=client, storage_root=tmp_path)
    assert attempts == 3
    assert stored.media_type == "text/html"

    attempts = 0

    async def bad_request(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(bad_request)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await download_attachment(ref, client=client, storage_root=tmp_path)
    assert attempts == 1

    async def oversize(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf", "content-length": "999"},
            content=b"small",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(oversize)) as client:
        with pytest.raises(ValueError, match="content length"):
            await download_attachment(
                AttachmentDownloadRef(
                    source_url="https://files.example.test/a.pdf",
                    filename="a.pdf",
                    declared_media_type="application/pdf",
                    allowed_source_host="files.example.test",
                ),
                client=client,
                storage_root=tmp_path,
                max_bytes=100,
            )


@pytest.mark.asyncio
async def test_pdf_native_parse_preserves_page_provenance(tmp_path: Path) -> None:
    content = _pdf_bytes("First page evidence", "Second page evidence")
    checksum = hashlib.sha256(content).hexdigest()
    attachment = StoredAttachment(
        sha256=checksum,
        byte_size=len(content),
        media_type="application/pdf",
        filename="specification.pdf",
        storage_key=f"sha256/{checksum[:2]}/{checksum}.blob",
        original_bytes=content,
    )

    parsed = parse_document(attachment)

    assert parsed.parser_kind == "native_pdf"
    assert parsed.parser_version
    assert parsed.checksum == attachment.sha256
    assert parsed.page_count == 2
    assert [(page.page_number, page.text.strip()) for page in parsed.pages] == [
        (1, "First page evidence"),
        (2, "Second page evidence"),
    ]


@pytest.mark.asyncio
async def test_empty_pdf_and_unsupported_hwp_are_never_trusted(tmp_path: Path) -> None:
    empty_pdf = _pdf_bytes("")
    empty_checksum = hashlib.sha256(empty_pdf).hexdigest()
    pdf = StoredAttachment(
        sha256=empty_checksum,
        byte_size=len(empty_pdf),
        media_type="application/pdf",
        filename="empty.pdf",
        storage_key=f"sha256/{empty_checksum[:2]}/{empty_checksum}.blob",
        original_bytes=empty_pdf,
    )
    pdf_quality = assess_text_quality(parse_document(pdf))
    assert pdf_quality.status == "needs_ocr"
    assert "empty_text" in pdf_quality.reasons

    hwp_content = b"HWP Document File\x00synthetic"
    hwp_checksum = hashlib.sha256(hwp_content).hexdigest()
    hwp = StoredAttachment(
        sha256=hwp_checksum,
        byte_size=len(hwp_content),
        media_type="application/x-hwp",
        filename="spec.hwp",
        storage_key=f"sha256/{hwp_checksum[:2]}/{hwp_checksum}.blob",
        original_bytes=hwp_content,
    )
    parsed_hwp = parse_document(hwp)
    assert parsed_hwp.parser_kind == "hwp_adapter"
    assert parsed_hwp.status == "unsupported"
    assert assess_text_quality(parsed_hwp).status == "unsupported"


@pytest.mark.asyncio
async def test_html_parse_strips_executable_content_and_keeps_text(tmp_path: Path) -> None:
    content = b"<h1>Notice</h1><script>alert('never run')</script><p>Deadline 2026-10-01</p>"
    checksum = hashlib.sha256(content).hexdigest()
    attachment = StoredAttachment(
        sha256=checksum,
        byte_size=len(content),
        media_type="text/html",
        filename="spec.html",
        storage_key=f"sha256/{checksum[:2]}/{checksum}.blob",
        original_bytes=content,
    )

    parsed = parse_document(attachment)

    assert parsed.parser_kind == "html"
    assert parsed.page_count == 1
    assert "Notice" in parsed.extracted_text
    assert "Deadline 2026-10-01" in parsed.extracted_text
    assert "alert" not in parsed.extracted_text


@pytest.mark.asyncio
async def test_persisted_pipeline_keeps_version_provenance_while_reusing_blob(
    session: AsyncSession, tmp_path: Path
) -> None:
    source = SourceRegistry(
        code="document-test", display_name="Document test", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    opportunity = Opportunity(
        canonical_key="document-test:notice", title="Notice", buyer_name="Buyer"
    )
    session.add(opportunity)
    await session.flush()
    versions: list[OpportunityVersion] = []
    for number in (1, 2):
        raw = RawRecord(
            source_id=source.id,
            source_record_id=f"notice-{number}",
            payload_json={},
            payload_sha256=str(number) * 64,
        )
        session.add(raw)
        await session.flush()
        version = OpportunityVersion(
            opportunity_id=opportunity.id,
            raw_record_id=raw.id,
            version_number=number,
            source_record_id=raw.source_record_id,
            normalized_json={},
            normalized_sha256=str(number + 2) * 64,
        )
        session.add(version)
        await session.flush()
        versions.append(version)

    ref = AttachmentRef(
        attachment_id="synthetic-specification",
        filename="synthetic-specification.html",
        url="https://example.invalid/synthetic-specification.html",
        media_type="text/html",
        fixture_key="synthetic-specification.html",
    )
    for version in versions:
        await persist_and_parse_attachments(
            session,
            opportunity_version_id=version.id,
            refs=[ref],
            allowed_source_host="example.invalid",
            storage_root=tmp_path,
        )
    await session.flush()

    attachments = (
        await session.scalars(
            select(Attachment)
            .where(Attachment.opportunity_version_id.in_([version.id for version in versions]))
            .order_by(Attachment.opportunity_version_id)
        )
    ).all()
    parses = (
        await session.scalars(
            select(DocumentParse)
            .join(Attachment, Attachment.id == DocumentParse.attachment_id)
            .where(Attachment.opportunity_version_id.in_([version.id for version in versions]))
            .order_by(DocumentParse.attachment_id)
        )
    ).all()
    assert len(attachments) == 2
    assert attachments[0].opportunity_version_id != attachments[1].opportunity_version_id
    assert attachments[0].sha256 == attachments[1].sha256
    assert attachments[0].storage_key == attachments[1].storage_key
    assert all(item.download_status == "parsed" for item in attachments)
    assert len(parses) == 2
    assert all(item.status == "trusted" for item in parses)
    assert all(item.quality_json["pages"][0]["page_number"] == 1 for item in parses)

    await persist_and_parse_attachments(
        session,
        opportunity_version_id=versions[0].id,
        refs=[ref],
        allowed_source_host="example.invalid",
        storage_root=tmp_path,
    )
    await session.flush()
    assert (
        len(
            (
                await session.scalars(
                    select(Attachment).where(
                        Attachment.opportunity_version_id.in_([version.id for version in versions])
                    )
                )
            ).all()
        )
        == 2
    )


@pytest.mark.asyncio
async def test_corrupt_pdf_keeps_download_metadata_and_failed_parse(
    session: AsyncSession, tmp_path: Path
) -> None:
    source = SourceRegistry(
        code="corrupt-document", display_name="Corrupt", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    raw = RawRecord(
        source_id=source.id,
        source_record_id="corrupt",
        payload_json={},
        payload_sha256="a" * 64,
    )
    opportunity = Opportunity(
        canonical_key="corrupt-document:notice", title="Notice", buyer_name="Buyer"
    )
    session.add_all([raw, opportunity])
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=opportunity.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id="corrupt",
        normalized_json={},
        normalized_sha256="b" * 64,
    )
    session.add(version)
    await session.flush()
    ref = AttachmentRef(
        attachment_id="corrupt-pdf",
        filename="corrupt.pdf",
        url="https://example.invalid/corrupt.pdf",
        media_type="application/pdf",
        fixture_key="corrupt.pdf",
    )

    processed = await persist_and_parse_attachments(
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
    parse = await session.scalar(
        select(DocumentParse).where(DocumentParse.attachment_id == attachment.id)
    )
    assert processed == 0
    assert attachment.sha256 == hashlib.sha256(b"%PDF-corrupt\n").hexdigest()
    assert attachment.storage_key is not None
    assert attachment.download_status == "parse_failed"
    assert parse.status == "failed"
    assert parse.quality_json == {"error": "invalid_pdf"}


@pytest.mark.asyncio
async def test_reconciliation_runs_packaged_pdf_pipeline_from_normalized_version(
    session: AsyncSession, tmp_path: Path
) -> None:
    source = SourceRegistry(
        code="mock", display_name="Synthetic mock source", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    raw = RawRecord(
        source_id=source.id,
        source_record_id="synthetic-pre-spec-001",
        payload_json={"title": "Synthetic", "buyer_name": "Synthetic Buyer"},
        payload_sha256="c" * 64,
        normalization_status="normalized",
    )
    opportunity = Opportunity(
        canonical_key="mock:pdf", title="Synthetic", buyer_name="Synthetic Buyer"
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

    result = await reconcile_pending_documents(
        {"session": session, "attachment_storage_path": tmp_path}
    )

    attachments = (
        await session.scalars(
            select(Attachment)
            .where(Attachment.opportunity_version_id == version.id)
            .order_by(Attachment.source_url)
        )
    ).all()
    parses = (
        await session.scalars(
            select(DocumentParse)
            .join(Attachment, Attachment.id == DocumentParse.attachment_id)
            .where(Attachment.opportunity_version_id == version.id)
        )
    ).all()
    assert result == {"processed": 2, "failed": 0}
    assert len(attachments) == 2
    assert all(item.sha256 is not None and item.storage_key is not None for item in attachments)
    assert sorted(parse.parser_kind for parse in parses) == ["native_pdf", "native_pdf", "ocr"]
    assert all(parse.page_count == 2 for parse in parses)
    assert all(
        [page["page_number"] for page in parse.quality_json["pages"]] == [1, 2]
        for parse in parses
    )

    repeated = await reconcile_pending_documents(
        {"session": session, "attachment_storage_path": tmp_path}
    )
    assert repeated == {"processed": 0, "failed": 0}
