from __future__ import annotations

import hashlib
import sys
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.documents import download, service
from app.documents.ocr_runtime import TesseractOcrAdapter
from app.models import (
    Attachment,
    DocumentParse,
    Opportunity,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
)
from app.sources.base import AttachmentRef
from tests.ocr_runtime.test_runtime import korean_scan, model_directory

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux OCR worker runtime")


@pytest.mark.asyncio
async def test_configured_real_ocr_is_persisted_once_and_preserves_native_parse(
    session, tmp_path, monkeypatch,
):
    settings = Settings(_env_file=None, ocr_backend="tesseract", ocr_tessdata_dir=model_directory())
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    async def resolve(_):
        return ("93.184.216.34",)

    monkeypatch.setattr(download, "_resolve_public_addresses", resolve)
    source = SourceRegistry(code=uuid4().hex, display_name="Synthetic runtime test",
                            base_url="https://example.invalid")
    session.add(source)
    await session.flush()
    content = korean_scan()
    raw = RawRecord(source_id=source.id, source_record_id=uuid4().hex, payload_json={},
                    payload_sha256="a" * 64)
    opportunity = Opportunity(canonical_key=uuid4().hex, title="OCR test", buyer_name="Test")
    session.add_all([raw, opportunity])
    await session.flush()
    version = OpportunityVersion(opportunity_id=opportunity.id, raw_record_id=raw.id,
                                 version_number=1, source_record_id=raw.source_record_id,
                                 normalized_json={}, normalized_sha256="b" * 64)
    session.add(version)
    await session.flush()
    ref = AttachmentRef(attachment_id="korean", filename="korean.pdf",
                        url="https://example.invalid/korean.pdf", media_type="application/pdf")
    calls = 0
    recognize = TesseractOcrAdapter.recognize

    async def count(self, document):
        nonlocal calls
        calls += 1
        return await recognize(self, document)

    monkeypatch.setattr(TesseractOcrAdapter, "recognize", count)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=content, headers={"content-type": "application/pdf"})
    )) as client:
        arguments = dict(opportunity_version_id=version.id, refs=[ref],
                         allowed_source_host="example.invalid", storage_root=tmp_path,
                         client=client)
        await service.persist_and_parse_attachments(session, **arguments)
        await service.persist_and_parse_attachments(session, **arguments)
    assert calls == 1
    attachment = await session.scalar(select(Attachment).where(
        Attachment.opportunity_version_id == version.id,
    ))
    rows = (await session.scalars(select(DocumentParse).where(
        DocumentParse.attachment_id == attachment.id,
    ))).all()
    assert len(rows) == 2
    native = next(row for row in rows if row.parser_kind == "native_pdf")
    ocr = next(row for row in rows if row.parser_kind == "ocr")
    assert native.status == "needs_ocr" and not (native.extracted_text or "").strip()
    assert ocr.quality_json["provider"] == "tesseract_pymupdf"
    assert ocr.quality_json["recognition_status"] == "recognized"
    assert "합성연구소" in "".join(ocr.extracted_text.split())
    assert ocr.text_sha256 == hashlib.sha256(ocr.extracted_text.encode()).hexdigest()
    assert attachment.sha256 == hashlib.sha256(content).hexdigest()
