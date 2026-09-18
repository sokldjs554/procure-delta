from copy import deepcopy

import pytest

from app.extraction.schemas import DocumentBundle, DocumentPage, ExtractionResult
from app.extraction.validation import validate_extraction


def bundle(text: str) -> DocumentBundle:
    if not any(line.startswith("Title:") for line in text.splitlines()):
        text += "\nTitle: Synthetic notice"
    text += "\nBuyer: Synthetic Buyer\nCategory: services"
    return DocumentBundle(
        pages=(
            DocumentPage(
                attachment_sha256="a" * 64,
                page_number=1,
                text=text,
                parser_kind="native_html",
                parser_version="1",
            ),
        )
    )


def proposal(field: str, value: object, quote: str) -> ExtractionResult:
    result = ExtractionResult(
        output={
            "schema_version": "1",
            "buyer_name": "Synthetic Buyer",
            "procurement_type": "services",
            "title": "Synthetic notice",
            field: value,
            "evidence": {
                "title": [
                    {
                        "attachment_sha256": "a" * 64,
                        "page_number": 1,
                        "quote": "Title: Synthetic notice",
                    }
                ],
                "buyer_name": [
                    {
                        "attachment_sha256": "a" * 64,
                        "page_number": 1,
                        "quote": "Buyer: Synthetic Buyer",
                    }
                ],
                "procurement_type": [
                    {"attachment_sha256": "a" * 64, "page_number": 1, "quote": "Category: services"}
                ],
                field: [{"attachment_sha256": "a" * 64, "page_number": 1, "quote": quote}],
            },
        }
    )
    if field in {"estimated_amount", "currency"}:
        other = "currency" if field == "estimated_amount" else "estimated_amount"
        result.output[other] = "KRW" if other == "currency" else "100"
        result.output["evidence"][other] = deepcopy(result.output["evidence"][field])
    return result


@pytest.mark.parametrize(
    ("field", "value", "quote"),
    [
        ("estimated_amount", "-1", "Budget: KRW -1"),
        ("estimated_amount", "10000000000000000", "Budget: KRW 10000000000000000"),
        ("currency", "BTC", "Budget: BTC 100"),
        ("procurement_type", "unknown", "Category: unknown"),
        ("closes_at", "not-a-date", "Deadline: not-a-date"),
        ("closes_at", "2026-09-30T18:00:00", "Deadline: 2026-09-30T18:00:00"),
        ("unknown_field", "value", "Unknown: value"),
    ],
)
def test_schema_rejects_unsupported_values(field: str, value: object, quote: str) -> None:
    report = validate_extraction(proposal(field, value, quote), bundle(quote))
    assert not report.valid
    assert report.errors


def test_date_order_is_rejected() -> None:
    result = proposal("title", "Synthetic notice", "Title: Synthetic notice")
    result.output.update(published_at="2026-10-01T00:00:00Z", closes_at="2026-09-01T00:00:00Z")
    report = validate_extraction(result, bundle(""))
    assert not report.valid
    assert "closing date precedes publication" in report.errors[0]


def test_valid_schema_has_no_manufactured_usage() -> None:
    result = proposal("title", "Synthetic notice", "Title: Synthetic notice")
    report = validate_extraction(result, bundle("Title: Synthetic notice"))
    assert report.valid
    assert report.fields is not None
    assert result.prompt_tokens is None and result.estimated_cost is None


def test_missing_evidence_and_empty_output_rejected() -> None:
    result = proposal("title", "Synthetic notice", "Title: Synthetic notice")
    output = deepcopy(result.output)
    output["evidence"] = {}
    assert not validate_extraction(ExtractionResult(output=output), bundle("")).valid
    assert not validate_extraction(ExtractionResult(output={}), bundle("")).valid


@pytest.mark.parametrize("missing", ["title", "buyer_name", "procurement_type"])
def test_required_field_absence_is_not_trusted(missing: str) -> None:
    result = proposal("title", "Synthetic notice", "Title: Synthetic notice")
    del result.output[missing]
    del result.output["evidence"][missing]
    assert not validate_extraction(result, bundle("Title: Synthetic notice")).valid
