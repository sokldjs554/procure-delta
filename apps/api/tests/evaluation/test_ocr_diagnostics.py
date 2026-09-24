from __future__ import annotations

import asyncio
import json

import pytest

from app.evaluation.ocr import score_text

PRIVATE = "private-source-value-never-publish"
VALID = f"Title: {PRIVATE}\nBuyer: Agency\nCategory: services"


@pytest.mark.parametrize("text,fields", [
    ("", ["buyer_name", "procurement_type", "title"]),
    (f"Title: {PRIVATE}", ["buyer_name", "procurement_type"]),
    (f"Title: {PRIVATE}\nBuyer: Agency\nCategory: invalid-private-category",
     ["procurement_type"]),
    (VALID + f"\nContract period: {PRIVATE}", ["unknown"]),
])
def test_schema_rejection_exposes_only_field_names(text, fields):
    result = asyncio.run(score_text(text, {"title": PRIVATE}))
    assert result["rejection_stage"] == "schema"
    assert result["schema_error_fields"] == fields
    assert result["grounding_issues"] == []
    assert not result["downstream_valid"]
    assert result["trusted_field_metrics"]["correct"] == 0
    assert PRIVATE not in json.dumps(result)
    assert "invalid-private-category" not in json.dumps(result)


def test_conflicting_ocr_claims_reach_grounding_diagnostics_without_text():
    result = asyncio.run(score_text(VALID + "\nTitle: Another private title", {"title": PRIVATE}))
    assert result["rejection_stage"] == "grounding"
    assert result["schema_error_fields"] == []
    assert {("title", "contradictory_claims")} <= {
        (item["field"], item["code"]) for item in result["grounding_issues"]
    }
    assert result["field_metrics"]["correct"] == 1
    assert result["trusted_field_metrics"]["correct"] == 0
    assert PRIVATE not in json.dumps(result)
    assert "Another private title" not in json.dumps(result)


def test_valid_but_inaccurate_output_is_not_a_validation_rejection():
    result = asyncio.run(score_text(VALID, {"title": "Different annotated title"}))
    assert result["downstream_valid"]
    assert result["rejection_stage"] is None
    assert result["schema_error_fields"] == result["grounding_issues"] == []
    assert result["trusted_field_metrics"]["correct"] == 0
    assert PRIVATE not in json.dumps(result)
