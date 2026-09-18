from __future__ import annotations

import importlib
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.models import OpportunityVersion, RawRecord


def engine() -> Any:
    # Fail as an assertion until the new public interface exists.
    assert importlib.util.find_spec("app.delta") is not None, "delta engine is not implemented"
    return importlib.import_module("app.delta.engine")


def snapshot(number: int, fields: dict[str, Any], attachments: tuple[Any, ...] = ()) -> Any:
    source_id = UUID(int=1)
    raw = RawRecord(
        id=UUID(int=number + 10),
        source_id=source_id,
        source_record_id="synthetic-delta",
        payload_json=deepcopy(fields),
        payload_sha256=str(number) * 64,
    )
    version = OpportunityVersion(
        id=UUID(int=number + 20),
        opportunity_id=UUID(int=2),
        raw_record_id=raw.id,
        version_number=number,
        source_record_id=raw.source_record_id,
        effective_at=datetime(2026, 9, number, tzinfo=UTC),
        normalized_json=deepcopy(fields),
        normalized_sha256=str(number) * 64,
    )
    return engine().DeltaSnapshot(version=version, raw=raw, attachments=attachments)


@pytest.mark.parametrize(
    ("field", "before", "after", "code", "level"),
    [
        ("estimated_amount", "100", "120", "budget_increased", "medium"),
        ("estimated_amount", "120", "100", "budget_decreased", "medium"),
        ("currency", "KRW", "USD", "budget_currency_changed", "medium"),
        (
            "closes_at",
            "2026-09-30T09:00:00+00:00",
            "2026-09-29T09:00:00+00:00",
            "deadline_earlier",
            "high",
        ),
        (
            "closes_at",
            "2026-09-30T09:00:00+00:00",
            "2026-10-02T09:00:00+00:00",
            "deadline_later",
            "medium",
        ),
        ("regions", [], ["Seoul"], "region_restriction_added", "high"),
        ("regions", ["Seoul"], [], "region_restriction_removed", "medium"),
        ("regions", ["Seoul"], ["Busan"], "region_restriction_changed", "high"),
        ("required_certifications", [], ["ISO 27001"], "certification_added", "high"),
        ("required_certifications", ["ISO 27001"], [], "certification_removed", "medium"),
        ("required_capabilities", [], ["Python"], "capability_added", "high"),
        ("required_capabilities", ["Python"], [], "capability_removed", "medium"),
        (
            "participation_constraints",
            ["Public liability coverage"],
            ["On-site staff required"],
            "material_clause_changed",
            "high",
        ),
        (
            "contract_period",
            "2026-10-01/2027-01-01",
            "2026-10-01/2027-03-01",
            "contract_period_changed",
            "medium",
        ),
    ],
)
def test_machine_changes_have_actual_before_after_evidence(
    field: str,
    before: Any,
    after: Any,
    code: str,
    level: str,
) -> None:
    old = {"estimated_amount": "100", "currency": "KRW", field: before}
    new = {**old, field: after}
    delta = engine().compute_delta(snapshot(1, old), snapshot(2, new))
    key = "budget" if field in {"estimated_amount", "currency"} else field
    change = delta.field_changes_json[key]
    if key == "budget":
        assert change["before"] == {k: old[k] for k in ("estimated_amount", "currency")}
        assert change["after"] == {k: new[k] for k in ("estimated_amount", "currency")}
    else:
        assert change["before"] == before
        assert change["after"] == after
    assert change["before_evidence"][0]["raw_record_id"] == str(UUID(int=11))
    assert change["after_evidence"][0]["raw_record_id"] == str(UUID(int=12))
    assert delta.impact_level == level
    assert code in delta.impact_reasons_json["codes"]


def test_equivalent_decimal_timezone_and_set_order_do_not_emit_changes() -> None:
    before = snapshot(
        1,
        {
            "estimated_amount": "100.00",
            "currency": "KRW",
            "regions": ["Seoul", "Busan"],
            "closes_at": "2026-09-30T09:00:00+09:00",
        },
    )
    after = snapshot(
        2,
        {
            "estimated_amount": "100",
            "currency": "KRW",
            "regions": ["Busan", "Seoul"],
            "closes_at": "2026-09-30T00:00:00Z",
        },
    )
    delta = engine().compute_delta(before, after)
    assert delta.field_changes_json == {}
    assert delta.impact_level == "low"
    assert delta.impact_reasons_json["codes"] == []


def test_attachment_manifest_detects_replacement_without_normalized_attachments() -> None:
    from app.models import Attachment

    old = Attachment(
        id=UUID(int=31),
        source_url="https://example.invalid/spec",
        sha256="a" * 64,
        filename="spec.html",
        opportunity_version_id=UUID(int=21),
    )
    new = Attachment(
        id=UUID(int=32),
        source_url=old.source_url,
        sha256="b" * 64,
        filename="spec.html",
        opportunity_version_id=UUID(int=22),
    )
    result = engine().compute_delta(snapshot(1, {}, (old,)), snapshot(2, {}, (new,)))
    change = result.document_changes_json["attachments"][0]
    assert change["kind"] == "replaced"
    assert change["before"]["sha256"] == "a" * 64
    assert change["after"]["sha256"] == "b" * 64
    assert change["before_evidence"][0]["attachment_id"] == str(old.id)
    assert result.impact_level == "medium"
    assert result.impact_reasons_json["codes"] == ["attachment_replaced"]


def test_optional_explanation_cannot_mutate_deterministic_result() -> None:
    result = engine().compute_delta(
        snapshot(1, {"regions": []}), snapshot(2, {"regions": ["Seoul"]})
    )
    original = deepcopy(result.field_changes_json)

    def malicious_explanation(payload: dict[str, Any]) -> str:
        payload["impact_level"] = "low"
        payload["field_changes"].clear()
        return "Informational prose only"

    assert engine().explain_delta(result, malicious_explanation) == "Informational prose only"
    assert result.field_changes_json == original
    assert result.impact_level == "high"


def test_rejects_cross_opportunity_and_reverse_observation_pairs() -> None:
    first, second = snapshot(1, {}), snapshot(2, {})
    with pytest.raises(ValueError, match="observation"):
        engine().compute_delta(second, first)
    second.version.opportunity_id = UUID(int=99)
    with pytest.raises(ValueError, match="opportunity"):
        engine().compute_delta(first, second)


def test_attachment_budget_keeps_currency_and_evidence_atomic() -> None:
    from dataclasses import replace

    from app.extraction.service import TrustedExtractionView

    evidence = {"attachment_sha256": "a" * 64, "page_number": 1, "quote": "Budget: KRW 200"}
    after = replace(
        snapshot(2, {"currency": "USD"}),
        extraction=TrustedExtractionView(
            fields={"estimated_amount": "200", "currency": "KRW"},
            evidence={"estimated_amount": [evidence], "currency": [evidence]},
            conflicts={},
        ),
    )
    delta = engine().compute_delta(
        snapshot(1, {"estimated_amount": "100", "currency": "KRW"}), after
    )
    budget = delta.field_changes_json["budget"]
    assert budget["after"] == {"estimated_amount": "200", "currency": "KRW"}
    assert {item["kind"] for item in budget["after_evidence"]} == {"attachment_claim"}


def test_missing_extracted_claim_is_unknown_not_requirement_removal() -> None:
    from dataclasses import replace

    from app.extraction.service import TrustedExtractionView

    before = replace(
        snapshot(1, {}),
        extraction=TrustedExtractionView(
            fields={"required_certifications": ["ISO 27001"]},
            evidence={
                "required_certifications": [
                    {
                        "attachment_sha256": "a" * 64,
                        "page_number": 1,
                        "quote": "Certifications: ISO 27001",
                    }
                ]
            },
            conflicts={},
        ),
    )
    result = engine().compute_delta(before, snapshot(2, {}))
    assert result.field_changes_json["required_certifications"]["after"] is None
    assert "certification_removed" not in result.impact_reasons_json["codes"]
    assert result.field_changes_json["required_certifications"]["after_evidence"] == []


def test_classification_is_independent_of_change_order() -> None:
    from app.delta.rules import classify_impact

    changes = {
        "regions": {"before": [], "after": ["Seoul"]},
        "required_certifications": {"before": ["ISO 27001"], "after": []},
        "attachments": [{"kind": "added"}],
    }
    result = classify_impact(changes)
    assert result.level == "high"
    assert result.reason_codes == (
        "attachment_added",
        "certification_removed",
        "region_restriction_added",
    )
    assert classify_impact(dict(reversed(list(changes.items())))) == result


@pytest.mark.parametrize("added", [True, False])
def test_attachment_addition_and_removal(added: bool) -> None:
    from app.models import Attachment

    item = Attachment(
        id=UUID(int=31),
        source_url="https://example.invalid/spec",
        sha256="a" * 64,
        filename="spec.html",
        opportunity_version_id=UUID(int=22 if added else 21),
    )
    result = engine().compute_delta(
        snapshot(1, {}, () if added else (item,)), snapshot(2, {}, (item,) if added else ())
    )
    assert result.impact_reasons_json["codes"] == [
        "attachment_added" if added else "attachment_removed"
    ]
    assert result.impact_level == ("low" if added else "medium")
