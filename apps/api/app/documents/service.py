from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.download import AttachmentDownloadRef, StoredAttachment, download_attachment
from app.documents.ocr import (
    FakeFixtureOcrAdapter,
    OcrAdapter,
    OcrDocument,
    ocr_parser_version,
    should_use_ocr,
)
from app.documents.parsers import PARSER_VERSION, ParsedDocument, ParsedPage, parse_document
from app.documents.quality import assess_text_quality
from app.models import Attachment, DocumentParse, OpportunityVersion
from app.sources.base import AttachmentRef


async def materialize_attachment_refs(
    session: AsyncSession,
    *,
    opportunity_version_id: UUID,
    refs: list[AttachmentRef],
    processing_generation: UUID | None = None,
) -> int:
    """Create durable per-version pending work before any external download."""
    version = (
        await session.scalars(
            select(OpportunityVersion)
            .where(OpportunityVersion.id == opportunity_version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).one()
    materialized = 0
    for ref in refs:
        result = await session.execute(
            insert(Attachment)
            .values(
                opportunity_version_id=opportunity_version_id,
                source_url=ref.url,
                filename=ref.filename,
                media_type=ref.media_type,
                download_status="pending",
            )
            .on_conflict_do_nothing(constraint="uq_attachment_version_source_url")
            .returning(Attachment.id)
        )
        if result.scalar_one_or_none() is not None:
            materialized += 1
    version.documents_discovered_at = datetime.now(UTC)
    version.documents_completed_at = None
    version.documents_generation = processing_generation or uuid4()
    return materialized


async def complete_document_generation(
    session: AsyncSession,
    *,
    opportunity_version_id: UUID,
    generation: UUID | None,
    gaps: dict[str, str],
) -> None:
    """Only the owner of the current processing generation may finalize readiness."""
    await session.execute(
        update(OpportunityVersion)
        .where(
            OpportunityVersion.id == opportunity_version_id,
            OpportunityVersion.documents_generation.is_not_distinct_from(generation),
        )
        .values(documents_completed_at=datetime.now(UTC), document_gaps_json=gaps)
    )


def _parsed_from_row(attachment: Attachment, row: DocumentParse) -> ParsedDocument:
    pages = tuple(
        ParsedPage(page_number=page["page_number"], text=page["text"])
        for page in row.quality_json.get("pages", [])
    )
    text = row.extracted_text or ""
    return ParsedDocument(
        checksum=attachment.sha256 or "",
        parser_kind=row.parser_kind,
        parser_version=row.parser_version,
        pages=pages,
        page_count=row.page_count or len(pages),
        extracted_text=text,
        text_sha256=row.text_sha256 or hashlib.sha256(text.encode()).hexdigest(),
        status="parsed",
    )


async def _persist_ocr(
    session: AsyncSession,
    *,
    attachment: Attachment,
    stored: StoredAttachment,
    parsed: ParsedDocument,
    fixture_key: str | None,
    adapter: OcrAdapter,
) -> bool:
    def completed(row: DocumentParse) -> bool:
        return (
            row.quality_json.get("recognition_status") == "recognized"
            or row.status == "unavailable"
        )

    parser_version = ocr_parser_version(adapter.provider, adapter.provider_version)
    existing = await session.scalar(
        select(DocumentParse).where(
            DocumentParse.attachment_id == attachment.id,
            DocumentParse.parser_kind == "ocr",
            DocumentParse.parser_version == parser_version,
        )
    )
    if existing is not None and completed(existing):
        return False
    legacy = await session.scalar(
        select(DocumentParse).where(
            DocumentParse.attachment_id == attachment.id,
            DocumentParse.parser_kind == "ocr",
            DocumentParse.parser_version == adapter.provider_version,
            DocumentParse.quality_json["provider"].astext == adapter.provider,
            DocumentParse.quality_json["provider_version"].astext == adapter.provider_version,
        )
    )
    if legacy is not None:
        legacy.parser_version = parser_version
        await session.flush()
        if completed(legacy):
            return False
    ocr = await adapter.recognize(
        OcrDocument(attachment=stored, native_parse=parsed, fixture_key=fixture_key)
    )
    if (ocr.provider, ocr.provider_version) != (adapter.provider, adapter.provider_version):
        raise ValueError("OCR result identity does not match configured adapter")
    ocr_quality = None
    if ocr.status == "recognized":
        ocr_quality = assess_text_quality(
            ParsedDocument(
                checksum=parsed.checksum,
                parser_kind="ocr",
                parser_version=parser_version,
                pages=ocr.pages,
                page_count=len(ocr.pages),
                extracted_text=ocr.extracted_text,
                text_sha256=ocr.text_sha256 or hashlib.sha256(b"").hexdigest(),
                status="parsed",
            )
        )
    quality_json = {
        "provider": ocr.provider,
        "provider_version": ocr.provider_version,
        "synthetic": ocr.synthetic,
        "recognition_status": ocr.status,
        "status": ocr_quality.status if ocr_quality is not None else "unavailable",
        "pages": [
            {
                "page_number": page.page_number,
                "text": page.text,
                "quality": {
                    "status": signal.status,
                    "reasons": list(signal.reasons),
                    "char_count": signal.char_count,
                    "non_whitespace_chars": signal.non_whitespace_chars,
                    "printable_ratio": signal.printable_ratio,
                    "alphanumeric_ratio": signal.alphanumeric_ratio,
                },
            }
            for page, signal in zip(
                ocr.pages,
                ocr_quality.page_signals if ocr_quality is not None else (),
                strict=True,
            )
        ],
    }
    await session.execute(
        insert(DocumentParse)
        .values(
            attachment_id=attachment.id,
            parser_kind="ocr",
            parser_version=parser_version,
            text_sha256=ocr.text_sha256,
            extracted_text=ocr.extracted_text or None,
            page_count=len(ocr.pages),
            quality_json=quality_json,
            status=ocr_quality.status if ocr_quality is not None else "unavailable",
        )
        .on_conflict_do_update(
            constraint="uq_document_parse_version",
            set_={
                "text_sha256": ocr.text_sha256,
                "extracted_text": ocr.extracted_text or None,
                "page_count": len(ocr.pages),
                "quality_json": quality_json,
                "status": ocr_quality.status if ocr_quality is not None else "unavailable",
            },
        )
    )
    return True


async def persist_and_parse_attachments(
    session: AsyncSession,
    *,
    opportunity_version_id: UUID,
    refs: list[AttachmentRef],
    allowed_source_host: str,
    storage_root: Path,
    client: httpx.AsyncClient | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    ocr_adapter: OcrAdapter | None = None,
    processing_generation: UUID | None = None,
) -> int:
    """Persist per-version provenance and idempotently create native parse records."""
    if processing_generation is None:
        await materialize_attachment_refs(
            session, opportunity_version_id=opportunity_version_id, refs=refs
        )
        version = await session.get_one(OpportunityVersion, opportunity_version_id)
        processing_generation = version.documents_generation
    else:
        version = (
            await session.scalars(
                select(OpportunityVersion)
                .where(OpportunityVersion.id == opportunity_version_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).one()
        if version.documents_generation != processing_generation:
            return 0  # A newer staging pass owns processing and completion now.
    await session.flush()
    processed = 0
    selected_ocr_adapter = ocr_adapter or FakeFixtureOcrAdapter()
    for ref in refs:
        attachment = await session.scalar(
            select(Attachment).where(
                Attachment.opportunity_version_id == opportunity_version_id,
                Attachment.source_url == ref.url,
            )
        )
        assert attachment is not None
        existing_parse = await session.scalar(
            select(DocumentParse)
            .where(
                DocumentParse.attachment_id == attachment.id,
                DocumentParse.parser_version == PARSER_VERSION,
                DocumentParse.parser_kind.in_(["native_pdf", "html", "hwp_adapter", "unsupported"]),
            )
            .limit(1)
        )
        if (
            attachment.download_status in {"parsed", "unsupported", "parse_failed"}
            and existing_parse is not None
        ):
            if existing_parse.status != "needs_ocr":
                continue
            if (
                attachment.sha256 is None
                or attachment.byte_size is None
                or attachment.media_type is None
                or attachment.storage_key is None
            ):
                raise ValueError("persisted attachment metadata is incomplete")
            content = (storage_root / attachment.storage_key).read_bytes()
            if hashlib.sha256(content).hexdigest() != attachment.sha256:
                raise ValueError("persisted attachment checksum mismatch")
            stored = StoredAttachment(
                sha256=attachment.sha256,
                byte_size=attachment.byte_size,
                media_type=attachment.media_type,
                filename=attachment.filename,
                storage_key=attachment.storage_key,
                original_bytes=content,
            )
            ocr_processed = await _persist_ocr(
                session,
                attachment=attachment,
                stored=stored,
                parsed=_parsed_from_row(attachment, existing_parse),
                fixture_key=ref.fixture_key,
                adapter=selected_ocr_adapter,
            )
            processed += int(ocr_processed)
            continue
        stored = await download_attachment(
            AttachmentDownloadRef(
                source_url=ref.url,
                filename=ref.filename,
                declared_media_type=ref.media_type,
                allowed_source_host=allowed_source_host,
                fixture_key=ref.fixture_key,
            ),
            client=client,
            storage_root=storage_root,
            max_bytes=max_bytes,
        )
        attachment.filename = stored.filename
        attachment.media_type = stored.media_type
        attachment.sha256 = stored.sha256
        attachment.byte_size = stored.byte_size
        attachment.storage_key = stored.storage_key
        await session.flush()
        try:
            parsed = parse_document(stored)
        except Exception:
            attachment.download_status = "parse_failed"
            await session.execute(
                insert(DocumentParse)
                .values(
                    attachment_id=attachment.id,
                    parser_kind="native_pdf"
                    if stored.media_type == "application/pdf"
                    else "unsupported",
                    parser_version=PARSER_VERSION,
                    text_sha256=None,
                    extracted_text=None,
                    page_count=None,
                    quality_json={
                        "error": "invalid_pdf"
                        if stored.media_type == "application/pdf"
                        else "parse_failed"
                    },
                    status="failed",
                )
                .on_conflict_do_update(
                    constraint="uq_document_parse_version",
                    set_={"quality_json": {"error": "invalid_pdf"}, "status": "failed"},
                )
            )
            continue
        quality = assess_text_quality(parsed)
        attachment.download_status = "unsupported" if parsed.status == "unsupported" else "parsed"
        quality_json = {
            "status": quality.status,
            "reasons": list(quality.reasons),
            "char_count": quality.char_count,
            "non_whitespace_chars": quality.non_whitespace_chars,
            "printable_ratio": quality.printable_ratio,
            "alphanumeric_ratio": quality.alphanumeric_ratio,
            "pages": [
                {
                    "page_number": page.page_number,
                    "text": page.text,
                    "quality": {
                        "status": signal.status,
                        "reasons": list(signal.reasons),
                        "char_count": signal.char_count,
                        "non_whitespace_chars": signal.non_whitespace_chars,
                        "printable_ratio": signal.printable_ratio,
                        "alphanumeric_ratio": signal.alphanumeric_ratio,
                    },
                }
                for page, signal in zip(parsed.pages, quality.page_signals, strict=True)
            ],
        }
        await session.execute(
            insert(DocumentParse)
            .values(
                attachment_id=attachment.id,
                parser_kind=parsed.parser_kind,
                parser_version=parsed.parser_version,
                text_sha256=parsed.text_sha256,
                extracted_text=parsed.extracted_text,
                page_count=parsed.page_count,
                quality_json=quality_json,
                status=quality.status,
            )
            .on_conflict_do_update(
                constraint="uq_document_parse_version",
                set_={
                    "text_sha256": parsed.text_sha256,
                    "extracted_text": parsed.extracted_text,
                    "page_count": parsed.page_count,
                    "quality_json": quality_json,
                    "status": quality.status,
                },
            )
        )
        if should_use_ocr(quality):
            # Native provenance must survive an external OCR provider failure so
            # the worker can retry OCR from the durable checksum blob.
            await session.commit()
            await _persist_ocr(
                session,
                attachment=attachment,
                stored=stored,
                parsed=parsed,
                fixture_key=ref.fixture_key,
                adapter=selected_ocr_adapter,
            )
        processed += 1
    # Native/OCR recovery commits release the initial row lock. Only this run's
    # generation may reopen the gate; an older OCR completion cannot finish a repair.
    await complete_document_generation(
        session,
        opportunity_version_id=opportunity_version_id,
        generation=processing_generation,
        gaps={},
    )
    return processed
