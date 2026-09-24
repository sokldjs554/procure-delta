from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest

from app.evaluation.runner import bundle, extraction_eval
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.schemas import ExtractionResult
from app.extraction.validation import validate_extraction

TEXT = "Title: Test notice\nBuyer: Test buyer\nCategory: services\nCapabilities: OCR"
PRIVATE = "secret-shaped-model-value-must-not-appear"


def valid_proposal(text=TEXT):
    document = bundle(text)
    return document, asyncio.run(DeterministicExtractor().extract(document))


def issue_pairs(report):
    return {(item.field, item.code) for item in report.grounding_issues}


@pytest.mark.parametrize("fault,expected", [
    ("missing", {("title", "missing_evidence")}),
    ("page", {("title", "evidence_not_on_page")}),
    ("checksum", {("title", "evidence_not_on_page")}),
    ("quote", {("title", "evidence_not_on_page"), ("title", "unsupported_value")}),
    ("value", {("title", "unsupported_value"), ("title", "contradictory_claims")}),
    ("conflict", {("title", "unsupported_value"), ("title", "contradictory_claims")}),
    ("qualified", {("required_capabilities", "qualified_requirement")}),
    ("unknown", {(None, "evidence_for_absent_field")}),
    ("absent", {(None, "evidence_for_absent_field")}),
])
def test_grounding_faults_have_safe_field_codes_without_changing_rejection(fault, expected):
    text = TEXT
    if fault == "conflict":
        text += "\nTitle: Another notice"
    if fault == "qualified":
        text += "\nCapabilities: OCR optional"
    document, result = valid_proposal(text)
    evidence = result.output["evidence"]
    if fault == "missing":
        evidence.pop("title")
    elif fault == "page":
        evidence["title"][0]["page_number"] = 2
    elif fault == "checksum":
        evidence["title"][0]["attachment_sha256"] = "b" * 64
    elif fault == "quote":
        evidence["title"][0]["quote"] = PRIVATE
    elif fault == "value":
        result.output["title"] = PRIVATE
    elif fault in {"unknown", "absent"}:
        evidence[PRIVATE if fault == "unknown" else "regions"] = [{
            **evidence["title"][0], "quote": PRIVATE,
        }]
    report = validate_extraction(result, document)
    assert not report.valid and report.fields is None
    assert issue_pairs(report) == expected
    encoded = json.dumps([item.model_dump() for item in report.grounding_issues])
    assert PRIVATE not in encoded
    assert document.pages[0].attachment_sha256 not in encoded
    assert "Test notice" not in encoded


def test_repeated_bad_references_produce_one_pair_per_failure():
    document, result = valid_proposal()
    bad_reference = {**result.output["evidence"]["title"][0], "quote": PRIVATE}
    result.output["evidence"]["title"] = [deepcopy(bad_reference) for _ in range(100)]
    report = validate_extraction(result, document)
    assert len(report.grounding_issues) == 2
    assert issue_pairs(report) == {("title", "evidence_not_on_page"),
                                   ("title", "unsupported_value")}


def test_success_and_schema_failure_do_not_invent_grounding_reasons():
    document, result = valid_proposal()
    report = validate_extraction(result, document)
    assert report.valid and report.grounding_issues == []
    result.output["procurement_type"] = PRIVATE
    report = validate_extraction(result, document)
    assert not report.valid and report.grounding_issues == []


def test_evaluation_projects_safe_grounding_reasons_and_keeps_rejected_usage():
    document, proposal = valid_proposal()
    proposal.output["evidence"][PRIVATE] = [{
        **proposal.output["evidence"]["title"][0], "quote": PRIVATE,
    }]

    class Stub:
        provider = "mock"
        model = "mock"
        extractor_version = "mock"

        async def extract(self, _):
            return ExtractionResult(output=proposal.output, prompt_tokens=13, completion_tokens=7)

    route = asyncio.run(extraction_eval([{
        "id": "safe-diagnostic", "text": document.pages[0].text,
        "expected_valid": True, "expected_fields": {"title": "Test notice"},
    }], Stub()))
    row = route["rows"][0]
    assert row["rejection_stage"] == "grounding"
    assert row["grounding_issues"] == [{"field": None, "code": "evidence_for_absent_field"}]
    assert row["trusted_fields"] == {}
    assert route["correct_fields"] == 0
    assert (route["prompt_tokens"], route["completion_tokens"]) == (13, 7)
    assert PRIVATE not in json.dumps(route)
