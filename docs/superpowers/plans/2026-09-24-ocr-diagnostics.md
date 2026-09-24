# OCR rejection diagnostics

**Goal:** Distinguish completed OCR recognition from schema and evidence rejection
in local OCR evaluation without publishing recognized values or validation messages.

**Design:** Extend `score_text` in `apps/api/app/evaluation/ocr.py` with
`rejection_stage`, `schema_error_fields` and `grounding_issues`, matching hosted
evaluation's existing safe vocabulary. Invalid schema uses known field names
or `unknown` for root/unknown locations. Grounding errors use the validator's
existing allowlisted codes. Valid output has no rejection stage even when it
disagrees with annotations. Recognition failures retain their existing separate
case status/reason. No production extraction, OCR settings, acceptance rules,
annotations or scoring denominator changes.

## Implementation and verification

- Add real-extractor tests in `tests/evaluation/test_ocr_diagnostics.py` for empty,
  partial and invalid-category text, contradictory titles, valid-but-inaccurate
  output, root schema errors, and absence of private source strings.
- Observe missing diagnostic keys fail before implementing the safe projection.
- Check propagation through `contract_tests/test_scan_ocr.py`: native empty text
  is rejected at schema; recognized valid text has no rejection stage.
- Run focused evaluation tests, all contract tests, Ruff and strict mypy.
- Publish a clean source commit, rerun the unchanged two original PDFs through
  the worker adapter, and save a new artifact without changing old measurements.
- Document measured diagnoses and limits in `docs/public-scan-ocr.md`; run the
  full backend/frontend/container CI and independent review before merging.

## Review focus

- Diagnostics must not include raw text, proposed values, arbitrary keys or
  Pydantic messages; root errors must not invent a particular failed field.
- A matching proposal rejected by grounding must still earn zero trusted fields.
- Accepted but inaccurate fields are accuracy failures, not validation rejection.
- Missing OCR output is not proof that the original document lacks that field.
- Additive diagnostics must propagate to original-scan results and retain all
  old metric values and frozen-case denominators.

## Execution record

Baseline: 12 grounding diagnostic tests passed on main `020f35d`.
RED: five cases failed because `rejection_stage` was absent.
GREEN: the same cases and 12 existing grounding tests passed; 46 contracts passed.
Root schema errors and scan propagation are additional boundary checks.
The user authorized continuing implementation and integration autonomously.
