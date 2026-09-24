from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credits.extraction import (
    ExtractionCreditPolicy,
    ExtractionCreditReviewRequired,
    assert_no_prior_attempt,
    assert_open_reservation,
    reserve_extraction,
    settle_extraction,
)
from app.documents.quality import assess_page_quality
from app.extraction.base import StructuredExtractor
from app.extraction.schemas import SCHEMA_VERSION, DocumentBundle, DocumentPage, ExtractionResult
from app.extraction.validation import GROUNDING_VERSION, validate_extraction
from app.models import Attachment, DocumentParse, OpportunityVersion, StructuredExtraction

BUDGET_FIELDS = {"estimated_amount", "currency"}


async def build_document_bundle(session: AsyncSession, version_id: UUID) -> DocumentBundle:
    rows = (
        await session.execute(
            select(Attachment, DocumentParse)
            .join(
                DocumentParse,
                DocumentParse.attachment_id == Attachment.id,
            )
            .where(
                Attachment.opportunity_version_id == version_id, DocumentParse.status == "trusted"
            )
            .order_by(Attachment.sha256, Attachment.id, DocumentParse.parser_version.desc())
        )
    ).all()
    selected: dict[UUID, tuple[Attachment, DocumentParse]] = {}
    for attachment, parsed in rows:
        if not attachment.sha256:
            continue
        if (
            parsed.parser_kind == "ocr"
            and parsed.quality_json.get("recognition_status") != "recognized"
        ):
            continue
        existing = selected.get(attachment.id)
        if existing is None or (parsed.parser_kind == "ocr" and existing[1].parser_kind != "ocr"):
            selected[attachment.id] = (attachment, parsed)
    pages = []
    for attachment, parsed in selected.values():
        for page in parsed.quality_json.get("pages", []):
            text = page.get("text", "")
            quality_status = page.get("quality", {}).get("status")
            if quality_status is None:
                # Old completed native parses predate per-page signals. Recompute
                # from saved text; never infer page suitability from aggregate trust.
                quality_status = assess_page_quality(text, page["page_number"]).status
            if quality_status == "trusted" and text.strip():
                pages.append(
                    DocumentPage(
                        attachment_sha256=attachment.sha256,
                        page_number=page["page_number"],
                        text=page["text"],
                        parser_kind=parsed.parser_kind,
                        parser_version=parsed.parser_version,
                    )
                )
    # Identical blobs attached through different URLs have identical provenance.
    unique = {page.model_dump_json(): page for page in pages}
    return DocumentBundle(pages=tuple(unique[key] for key in sorted(unique)))


def extraction_identity(document: DocumentBundle, extractor: StructuredExtractor) -> str:
    identity = [
        document.fingerprint,
        SCHEMA_VERSION,
        GROUNDING_VERSION,
        extractor.extractor_version,
        extractor.provider,
        extractor.model,
    ]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def _equivalent(field: str, upstream: Any, extracted: Any) -> bool:
    try:
        if field == "estimated_amount":
            return Decimal(str(upstream)) == Decimal(str(extracted))
        if field in {"published_at", "closes_at"}:
            return datetime.fromisoformat(
                upstream.replace("Z", "+00:00")
            ) == datetime.fromisoformat(extracted.replace("Z", "+00:00"))
        if isinstance(upstream, list) and isinstance(extracted, list):
            return set(upstream) == set(extracted)
    except (ValueError, TypeError):
        return False
    return bool(upstream == extracted)


async def persist_extraction(
    session: AsyncSession,
    version_id: UUID,
    extractor: StructuredExtractor,
    *,
    expected_key: str | None = None,
    credit_policy: ExtractionCreditPolicy | None = None,
) -> StructuredExtraction | None:
    # The lock covers the external call and insert. A completed replay never calls the provider.
    version = (
        await session.scalars(
            select(OpportunityVersion).where(OpportunityVersion.id == version_id).with_for_update()
        )
    ).one()
    document = await build_document_bundle(session, version_id)
    if not document.pages:
        return None
    key = extraction_identity(document, extractor)
    if expected_key is not None and key != expected_key:
        return None  # A stale queued job must not consume a newer input under its old identity.
    existing: StructuredExtraction | None = await session.scalar(
        select(StructuredExtraction).where(
            StructuredExtraction.opportunity_version_id == version_id,
            StructuredExtraction.extraction_key == key,
        )
    )
    if existing is not None:
        return existing
    await assert_no_prior_attempt(session, version_id, key)
    if credit_policy is None:
        return await _run_and_persist(session, version, extractor, document, key)

    ticket = await reserve_extraction(session, version_id, key, credit_policy)
    try:
        # Reservation commit released the lock. Recheck everything before I/O.
        version = (await session.scalars(
            select(OpportunityVersion).where(OpportunityVersion.id == version_id)
            .with_for_update().execution_options(populate_existing=True)
        )).one()
        await assert_open_reservation(session, credit_policy.account, ticket)
        current = await build_document_bundle(session, version_id)
        existing = await session.scalar(select(StructuredExtraction).where(
            StructuredExtraction.opportunity_version_id == version_id,
            StructuredExtraction.extraction_key == key,
        ))
        if not current.pages or extraction_identity(current, extractor) != key or existing:
            await settle_extraction(session, credit_policy.account, ticket, "refund")
            await session.commit()
            return existing
        row = await _run_and_persist(session, version, extractor, current, key)
        await settle_extraction(session, credit_policy.account, ticket, "commit")
        # The result and debit either both commit or neither commits.
        await session.commit()
        return row
    except Exception:
        # Do not guess whether the provider ran, or expose response text in an error.
        await session.rollback()
        raise ExtractionCreditReviewRequired("extraction attempt requires review") from None


async def _run_and_persist(
    session: AsyncSession, version: OpportunityVersion, extractor: StructuredExtractor,
    document: DocumentBundle, key: str,
) -> StructuredExtraction:
    started = time.perf_counter()
    result = await extractor.extract(document)
    latency_ms = round((time.perf_counter() - started) * 1000)
    report = validate_extraction(result, document)
    conflicts = {}
    if report.fields is not None:
        claims = report.fields.model_dump(
            mode="json", exclude_none=True, exclude={"schema_version", "evidence"}
        )
        for field, value in claims.items():
            upstream = version.normalized_json.get(field)
            if upstream is not None and upstream != [] and not _equivalent(field, upstream, value):
                conflicts[field] = {"upstream": upstream, "attachment": value}
        if BUDGET_FIELDS.intersection(conflicts):
            for field in BUDGET_FIELDS:
                conflicts.setdefault(
                    field,
                    {
                        "upstream": version.normalized_json.get(field),
                        "attachment": claims[field],
                        "reason": "amount_and_currency_conflict_group",
                    },
                )
    row = StructuredExtraction(
        opportunity_version_id=version.id,
        extractor_version=extractor.extractor_version,
        provider=extractor.provider,
        model=extractor.model,
        schema_version=SCHEMA_VERSION,
        extraction_key=key,
        input_fingerprint=document.fingerprint,
        input_bundle_json=document.model_dump(mode="json"),
        output_json=result.output,
        evidence_json=result.output.get("evidence", {})
        if isinstance(result.output.get("evidence", {}), dict)
        else {},
        validation_status="validated" if report.valid else "rejected",
        validation_errors_json={"errors": report.errors},
        conflicts_json=conflicts,
        latency_ms=latency_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        estimated_cost=result.estimated_cost,
    )
    session.add(row)
    await session.flush()
    return row


@dataclass(frozen=True)
class TrustedExtractionView:
    fields: dict[str, Any]
    evidence: dict[str, Any]
    conflicts: dict[str, Any]


async def trusted_extraction_view(
    session: AsyncSession, extraction_id: UUID
) -> TrustedExtractionView | None:
    """Return grounded, nonconflicting attachment claims; upstream history stays separate."""
    row = await session.get(StructuredExtraction, extraction_id)
    if row is None or row.validation_status != "validated":
        return None
    document = DocumentBundle.model_validate(row.input_bundle_json)
    if document.fingerprint != row.input_fingerprint:
        return None
    report = validate_extraction(ExtractionResult(output=row.output_json), document)
    if report.fields is None:
        return None
    fields = report.fields.model_dump(
        mode="json", exclude_none=True, exclude={"schema_version", "evidence"}
    )
    withheld = set(row.conflicts_json)
    # Apply the group at read time too: older rows retain their original conflict facts.
    if BUDGET_FIELDS.intersection(withheld):
        withheld.update(BUDGET_FIELDS)
    for field in withheld:
        fields.pop(field, None)
    evidence = {key: value for key, value in row.evidence_json.items() if key in fields}
    return TrustedExtractionView(fields=fields, evidence=evidence, conflicts=row.conflicts_json)
