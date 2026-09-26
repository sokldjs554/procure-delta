"""A sparse model proposal cannot hide invalid supported source claims."""

import asyncio

import pytest

from app.extraction.deterministic import DeterministicExtractor
from app.extraction.schemas import DocumentBundle, DocumentPage, ExtractionResult
from app.extraction.validation import validate_extraction

BASE = "Title: Example\nBuyer: Example Agency\nCategory: services"


def sparse_proposal(suffix: str) -> tuple[DocumentBundle, ExtractionResult]:
    document = DocumentBundle(pages=(DocumentPage(
        attachment_sha256="a" * 64, page_number=1, text=BASE + "\n" + suffix,
        parser_kind="native_text", parser_version="test",
    ),))
    output = {"schema_version": "1", "title": "Example", "buyer_name": "Example Agency",
              "procurement_type": "services", "evidence": {}}
    for field, quote in zip(("title", "buyer_name", "procurement_type"), BASE.splitlines(),
                            strict=True):
        output["evidence"][field] = [{
            "attachment_sha256": "a" * 64, "page_number": 1, "quote": quote,
        }]
    return document, ExtractionResult(output=output)


@pytest.mark.parametrize("suffix", [
    "Budget: KRW 0",
    "Budget: USD 10000000000000000",
    "Budget: KRW -1",
    "Budget: USD -1,000.50",
    "예산: -1원",
    "Published: 2026-02-30T00:00:00Z",
    "Deadline: 2026-02-30T00:00:00Z",
    "Published: 2026-02-30",
    "Deadline: 2026-02-30",
    "Published: 2026-13-01T00:00:00+09:00",
    "Deadline: 2026-09-26T25:00:00Z",
    "Deadline: 2026-09-26T00:60:00Z",
    "Deadline: 2026-09-26T00:00:60Z",
    "마감일: 2025-02-29 00:00 KST",
    "Contract period: 2026-12-31/2026-01-01",
    "Contract period: 2026-02-30/2026-12-31",
    "Published: 2026-09-26T00:00:00Z\nDeadline: 2026-09-25T00:00:00Z",
])
def test_omitting_invalid_supported_values_cannot_validate_document(suffix):
    document, proposal = sparse_proposal(suffix)
    report = validate_extraction(proposal, document)
    assert not report.valid
    assert report.fields is None
    assert any(issue.code == "invalid_source_claim" for issue in report.grounding_issues)
    assert "Example Agency" not in str([issue.model_dump() for issue in report.grounding_issues])


@pytest.mark.parametrize("suffix,field", [
    ("Budget: KRW 100\nBudget: KRW 200", "estimated_amount"),
    ("Region: Seoul\nRegion: Busan", "regions"),
    ("Deadline: 2026-09-25T00:00:00Z\nDeadline: 2026-09-26T00:00:00Z", "closes_at"),
])
def test_omitting_conflicting_supported_values_cannot_validate_document(suffix, field):
    document, proposal = sparse_proposal(suffix)
    report = validate_extraction(proposal, document)
    assert not report.valid
    assert (field, "contradictory_claims") in {
        (issue.field, issue.code) for issue in report.grounding_issues
    }


@pytest.mark.parametrize("suffix", [
    "Contract period: after contract signing",
    "Deadline: 2026-09-25",
    "Published: 2026-09-25T09:30:00",
    "Deadline: 2026-09-25T09:30:00",
    "Published: unknown",
    "Deadline: 2026-02-30 subject to confirmation",
    "Budget: budget pending",
    "Budget: KRW -1 is an example, not the budget",
    "Certifications: ISO 27001\nCertifications: optional ISO 9001",
    "Certifications: ISO 27001\nCertifications: ISO 9001\nCertifications: not required",
    "Budget: KRW 100",
])
def test_unsupported_qualified_or_valid_optional_omission_remains_conservative(suffix):
    document, proposal = sparse_proposal(suffix)
    report = validate_extraction(proposal, document)
    assert report.valid, report.errors
    assert set(report.fields.model_dump(exclude_none=True)) == {
        "schema_version", "title", "buyer_name", "procurement_type", "evidence",
    }


def test_source_conflict_on_another_attachment_is_not_hidden_by_omission():
    document, proposal = sparse_proposal("Budget: KRW 100")
    document = DocumentBundle(pages=(*document.pages, document.pages[0].model_copy(update={
        "attachment_sha256": "b" * 64, "text": "Budget: KRW 200",
    })))
    assert not validate_extraction(proposal, document).valid


@pytest.mark.parametrize("suffix", [
    "Budget: KRW -1",
    "Published: 2026-02-30T00:00:00Z",
    "Deadline: 2026-02-30T00:00:00Z",
])
def test_deterministic_extraction_does_not_silently_drop_invalid_literals(suffix):
    document, _ = sparse_proposal(suffix)
    proposal = asyncio.run(DeterministicExtractor().extract(document))
    assert not validate_extraction(proposal, document).valid


def test_a_valid_first_date_does_not_hide_a_later_malformed_literal():
    document, proposal = sparse_proposal(
        "Published: 2026-01-01T00:00:00Z\nPublished: 2026-02-30T00:00:00Z",
    )
    assert not validate_extraction(proposal, document).valid
