import json
from copy import deepcopy

import httpx
import pytest
from sqlalchemy import delete, select

from app.extraction.deterministic import DeterministicExtractor
from app.extraction.hosted import HostedExtractor
from app.extraction.service import (
    build_document_bundle,
    persist_extraction,
    trusted_extraction_view,
)
from app.models import Attachment, DocumentParse, OpportunityVersion
from app.sources.http import ResilientHttpClient
from tests.extraction.test_persistence import seeded as seeded
from tests.extraction.test_schema_validation import bundle


@pytest.mark.asyncio
async def test_legacy_pages_reassessed_without_blind_trust_or_rewriting(
    seeded, worker_session_factory
):
    async with worker_session_factory() as session:
        native = await session.scalar(
            select(DocumentParse)
            .join(Attachment)
            .where(
                Attachment.opportunity_version_id == seeded,
                DocumentParse.parser_kind == "native_pdf",
                DocumentParse.status == "trusted",
            )
        )
        attachment = await session.get_one(Attachment, native.attachment_id)
        native_id, checksum = native.id, attachment.sha256
        legacy = deepcopy(native.quality_json)
        for page in legacy["pages"]:
            page.pop("quality", None)
        legacy["pages"][1]["text"] = "!@#$%^&*()[]{}<>?/" * 3
        native.quality_json = legacy
        ids = select(Attachment.id).where(Attachment.opportunity_version_id == seeded)
        await session.execute(
            delete(DocumentParse).where(
                DocumentParse.attachment_id.in_(ids), DocumentParse.parser_kind == "ocr"
            )
        )
        await session.commit()

        document = await build_document_bundle(session, seeded)
        assert len(document.pages) == 1
        assert document.pages[0].page_number == 1
        assert document.pages[0].attachment_sha256 == checksum
        row = await persist_extraction(session, seeded, DeterministicExtractor())
        await session.commit()
        assert row is not None and row.validation_status == "rejected"
        assert row.input_bundle_json["pages"][0]["text"] == legacy["pages"][0]["text"]
        await session.refresh(native)
        assert native.id == native_id and native.quality_json == legacy


def overflow_response(location):
    content = '{"estimated_amount":1e400}'
    if location == "envelope":
        return '{"output":1e400}', '{"output":1e400}'
    return json.dumps(
        {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    ), content


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["envelope", "content"])
async def test_numeric_overflow_rejected_with_original_text(location):
    body, original = overflow_response(location)
    async with ResilientHttpClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    ) as client:
        row = await HostedExtractor(
            endpoint="https://provider.invalid/v1/chat/completions",
            provider="mock",
            model="v1",
            client=client,
        ).extract(bundle("Title: Synthetic notice"))
    assert row.output == {"_invalid_json": original}
    json.dumps(row.output, allow_nan=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["envelope", "content"])
async def test_numeric_overflow_persists_as_rejected(seeded, worker_session_factory, location):
    body, original = overflow_response(location)
    async with ResilientHttpClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    ) as client:
        extractor = HostedExtractor(
            endpoint="https://provider.invalid/v1/chat/completions",
            provider="mock",
            model="v1",
            client=client,
        )
        async with worker_session_factory() as session:
            row = await persist_extraction(session, seeded, extractor)
            await session.commit()
            assert row is not None and row.validation_status == "rejected"
            assert row.output_json == {"_invalid_json": original}
            assert await trusted_extraction_view(session, row.id) is None
            assert (await persist_extraction(session, seeded, extractor)).id == row.id


@pytest.mark.asyncio
@pytest.mark.parametrize("upstream", [{"currency": "KRW"}, {"estimated_amount": "200"}])
async def test_budget_conflict_withholds_both_value_and_unit(
    seeded, worker_session_factory, upstream
):
    async with worker_session_factory() as session:
        version = await session.get_one(OpportunityVersion, seeded)
        version.normalized_json = upstream
        ocr = await session.scalar(
            select(DocumentParse)
            .join(Attachment)
            .where(Attachment.opportunity_version_id == seeded, DocumentParse.parser_kind == "ocr")
        )
        quality = deepcopy(ocr.quality_json)
        quality["pages"][0]["text"] = quality["pages"][0]["text"].replace(
            "Budget: KRW 125,000,000", "Budget: USD 100"
        )
        ocr.quality_json = quality
        await session.commit()
        row = await persist_extraction(session, seeded, DeterministicExtractor())
        await session.commit()
        assert row.validation_status == "validated"
        view = await trusted_extraction_view(session, row.id)
        assert view is not None
        assert "estimated_amount" not in view.fields
        assert "currency" not in view.fields
        assert "estimated_amount" not in view.evidence
        assert "currency" not in view.evidence
        assert {"estimated_amount", "currency"} <= view.conflicts.keys()
        assert row.output_json["estimated_amount"] == "100"
        assert row.output_json["currency"] == "USD"
        await session.refresh(version)
        assert version.normalized_json == upstream

        # Older durable rows may only have recorded the directly conflicting field.
        direct_field = next(iter(upstream))
        row.conflicts_json = {direct_field: row.conflicts_json[direct_field]}
        await session.commit()
        legacy_view = await trusted_extraction_view(session, row.id)
        assert "estimated_amount" not in legacy_view.fields
        assert "currency" not in legacy_view.fields
