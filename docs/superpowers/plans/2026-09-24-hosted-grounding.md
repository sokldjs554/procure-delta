# Hosted Grounding Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline.

**Goal:** Make grounding failures diagnosable and align hosted requests with existing validation.

**Architecture:** Add typed, bounded diagnostics at the validator failure sites and project them into evaluation rows. Build a static system contract from the existing label maps/schema; include the actual prompt in extractor identity.

**Tech Stack:** Python, Pydantic, httpx, pytest, GitHub Actions.

**Spec:** [Hosted grounding contract](../../hosted-grounding-contract.md).

## Global Constraints

- Preserve validation decisions and raw historical artifacts.
- No raw model/document data in grounding diagnostics.
- No new paid triggers or repair calls; existing manual workflow only.
- Do not claim model quality improved before a new live measurement.

## Review Focus

- Unknown evidence keys must not leak into diagnostics.
- Repeated invalid references must not grow published diagnostics without bound.
- Empty, schema-invalid and successful outputs need distinct diagnostic behavior.
- Prompt/schema changes must invalidate request identity; identical requests remain stable.
- Timezone, qualification and exact-quote rules must match the existing validator.

### Task 1: Typed grounding reasons

**Files:** schemas.py, validation.py under apps/api/app/extraction; apps/api/app/evaluation/runner.py; apps/api/tests/evaluation/test_grounding_diagnostics.py.

**Interfaces:** `ValidationReport.grounding_issues: list[GroundingIssue]`; each issue exposes allowlisted `field` and `code`; evaluation rows expose JSON dictionaries.

- [ ] Write tests covering all six failure classes, unknown keys, repeated references, successful extraction and schema failure.
- [ ] Run `PYTHONPATH=apps/api ../procure-delta/.venv/bin/python -m pytest --confcutdir=apps/api/tests/evaluation apps/api/tests/evaluation/test_grounding_diagnostics.py -q`; expect missing diagnostic assertions to fail.
- [ ] Add `GroundingIssue` literals and a default-empty report list. Append issues at existing failure branches, deduplicate `(field, code)` pairs, and include them in evaluation rows without parsing error strings.
- [ ] Run the command again; expect every test to pass. Run the existing evaluation suite.
- [ ] Commit as `Explain grounding rejections without exposing model text`.

### Task 2: Explicit hosted contract

**Files:** apps/api/app/extraction/hosted.py; new prompt.py; apps/api/tests/evaluation/test_hosted_prompt_contract.py; docs/external-validation.md.

**Interfaces:** `extraction_system_prompt() -> str`, a static document-independent instruction containing the label maps, transformations and schema. `HostedExtractor` captures it and hashes it with endpoint/token limit for v3 identity.

- [ ] Add mock-HTTP tests checking the sent contract, separate untrusted input, repeat identity, changed-prompt identity and valid grounded Korean response handling.
- [ ] Run the focused new tests; expect the missing explicit contract and identity change assertions to fail.
- [ ] Implement the prompt; require plain JSON, exact spans/provenance, source-language strings, ordered semicolon lists, amount/currency pairing, KST publication dates, qualified optional omission, and abstention on mandatory gaps/conflicts. Keep the parser and validator acceptance unchanged.
- [ ] Run both new files plus the existing evaluation/extraction tests; expect green. Run Ruff, strict mypy and contract tests.
- [ ] Update reproduction docs with diagnostics and unmeasured quality boundary. Commit as `Describe the grounding contract in hosted requests`.
- [ ] Request fresh review, resolve material findings, publish the reviewed tree, require both push/PR CI runs, and merge the expected head. Check main CI and automatic demo deployment.
