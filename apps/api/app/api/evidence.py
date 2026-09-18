from __future__ import annotations

import hashlib
import re
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Owner, Session
from app.api.schemas import Document, Extraction, ExtractionSnapshot, Parse
from app.config import get_settings
from app.extraction.hosted import configured_extractor
from app.extraction.service import (
    build_document_bundle,
    extraction_identity,
    trusted_extraction_view,
)
from app.models import Attachment, DocumentParse, OpportunityVersion, StructuredExtraction

router = APIRouter(prefix="/api/v1", tags=["evidence"])


async def extraction_for(session: AsyncSession, version_id: UUID) -> Extraction:
    version = await session.get_one(OpportunityVersion, version_id)
    if version.documents_completed_at is None:
        return Extraction(status="documents_pending")
    document = await build_document_bundle(session, version_id)
    if not document.pages:
        return Extraction(status="no_suitable_pages")
    key = extraction_identity(document, configured_extractor(get_settings()))
    row = await session.scalar(
        select(StructuredExtraction).where(
            StructuredExtraction.opportunity_version_id == version_id,
            StructuredExtraction.extraction_key == key,
        )
    )
    if row is None:
        return Extraction(status="pending")
    return await extraction_snapshot(session, row)


async def extraction_snapshot(session: AsyncSession, row: StructuredExtraction) -> Extraction:
    view = await trusted_extraction_view(session, row.id)
    return Extraction(
        status=row.validation_status
        if view or row.validation_status != "validated"
        else "untrusted",
        id=row.id,
        extractor_version=row.extractor_version,
        schema_version=row.schema_version,
        input_fingerprint=row.input_fingerprint,
        trusted_fields=view.fields if view else {},
        evidence=view.evidence if view else {},
        conflicts=row.conflicts_json,
        validation_errors=row.validation_errors_json.get("errors", []),
    )


async def documents_for(session: AsyncSession, version_id: UUID) -> list[Document]:
    attachments = await session.scalars(
        select(Attachment)
        .where(Attachment.opportunity_version_id == version_id)
        .order_by(Attachment.id)
    )
    documents = []
    for attachment in attachments:
        parses = await session.scalars(
            select(DocumentParse)
            .where(DocumentParse.attachment_id == attachment.id)
            .order_by(DocumentParse.id)
        )
        documents.append(
            Document(
                id=attachment.id,
                filename=attachment.filename,
                media_type=attachment.media_type,
                sha256=attachment.sha256,
                byte_size=attachment.byte_size,
                download_status=attachment.download_status,
                original_url=f"/api/v1/documents/{attachment.id}/original"
                if attachment.storage_key and attachment.sha256
                else None,
                parses=[Parse.model_validate(parsed) for parsed in parses],
            )
        )
    return documents


@router.get("/opportunities/{identifier}/versions/{version_id}/evidence", response_model=Extraction)
async def version_evidence(
    identifier: UUID, version_id: UUID, session: Session, owner: Owner
) -> Extraction:
    version = await session.get(OpportunityVersion, version_id)
    if version is None or version.opportunity_id != identifier:
        raise HTTPException(404, "Version not found")
    return await extraction_for(session, version_id)


@router.get(
    "/opportunities/{identifier}/versions/{version_id}/extractions",
    response_model=list[ExtractionSnapshot],
)
async def extraction_history(
    identifier: UUID, version_id: UUID, session: Session, owner: Owner
) -> list[ExtractionSnapshot]:
    version = await session.get(OpportunityVersion, version_id)
    if version is None or version.opportunity_id != identifier:
        raise HTTPException(404, "Version not found")
    current = await extraction_for(session, version_id)
    rows = await session.scalars(
        select(StructuredExtraction)
        .where(
            StructuredExtraction.opportunity_version_id == version_id,
        )
        .order_by(StructuredExtraction.id)
    )
    return [
        ExtractionSnapshot(
            **(await extraction_snapshot(session, row)).model_dump(),
            applicable_now=row.id == current.id,
            proposal=row.output_json,
        )
        for row in rows
    ]


@router.get(
    "/opportunities/{identifier}/versions/{version_id}/documents", response_model=list[Document]
)
async def version_documents(
    identifier: UUID, version_id: UUID, session: Session, owner: Owner
) -> list[Document]:
    version = await session.get(OpportunityVersion, version_id)
    if version is None or version.opportunity_id != identifier:
        raise HTTPException(404, "Version not found")
    return await documents_for(session, version_id)


@router.get("/opportunities/{identifier}/evidence", response_model=Extraction)
async def current_evidence(identifier: UUID, session: Session, owner: Owner) -> Extraction:
    from app.models import Opportunity

    row = await session.get(Opportunity, identifier)
    if row is None:
        raise HTTPException(404, "Opportunity not found")
    return (
        await extraction_for(session, row.current_version_id)
        if row.current_version_id
        else Extraction(status="missing_version")
    )


@router.get("/documents/{identifier}/original")
async def original_document(identifier: UUID, session: Session, owner: Owner) -> Response:
    row = await session.get(Attachment, identifier)
    if row is None or row.sha256 is None or not re.fullmatch(r"[0-9a-f]{64}", row.sha256):
        raise HTTPException(404, "Document unavailable")
    expected = f"sha256/{row.sha256[:2]}/{row.sha256}.blob"
    root = get_settings().attachment_storage_path.resolve()
    path = (root / expected).resolve()
    if row.storage_key != expected or not path.is_relative_to(root):
        raise HTTPException(404, "Document unavailable")
    try:
        if path.stat().st_size > get_settings().attachment_max_bytes:
            raise HTTPException(409, "Document exceeds configured size limit")
        content = path.read_bytes()
    except OSError as exc:
        raise HTTPException(404, "Document unavailable") from exc
    if hashlib.sha256(content).hexdigest() != row.sha256:
        raise HTTPException(409, "Document integrity check failed")
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="document-{row.id}.bin"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "ETag": f'"{row.sha256}"',
            "Cache-Control": "private, no-store",
        },
    )
