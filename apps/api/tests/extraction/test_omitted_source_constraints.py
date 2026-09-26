"""A sparse model proposal cannot hide invalid supported source claims."""

import pytest

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
