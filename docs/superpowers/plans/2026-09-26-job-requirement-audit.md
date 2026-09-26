# Job Requirement Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans; preserve task ownership during parallel implementation.

**Goal:** Audit every StepAI requirement and fix reproduced scale, extraction, measurement and operational defects.
**Architecture:** Keep existing service boundaries, add bounded selectors and fail-closed checks, and preserve historical evidence. Extend the existing notification adapter with an explicit Slack format.
**Tech Stack:** Python/FastAPI/PostgreSQL/ARQ, Next.js/TypeScript, pytest, GitHub Actions.
**Spec:** `docs/superpowers/specs/2026-09-26-job-requirement-audit.md`.

## Global Constraints

- Existing synthetic measurements remain immutable historical evidence.
- No paid resource, payment, external message or hosted model call.
- Local pure tests are separate from real PostgreSQL/Redis integration in CI.
- No implicit customer billing policy; missing subscription/provider integration stays explicit.

## Review Focus

- Future retries and terminal normalization failures cannot starve later ready work.
- Omitted optional model fields cannot bypass an explicit invalid/conflicting source value.
- A valid historical measurement remains valid history even when the current contract differs.
- Error-tracking frame locals and source context cannot leak unclassified sensitive values.
- Slack text cannot create mentions from untrusted procurement content or treat an arbitrary 2xx as success.

### Task 1: Bounded normalization recovery

**Files:** `apps/api/app/workers/jobs.py`, `app/config.py`, normalization tests, `docs/data-pipeline.md`.
**Interfaces:** Existing poll/reconcile functions; `Settings.normalization_batch_size=100` (1–1000).

- [ ] Seed more than two batches and verify bounded calls, deterministic ordering and restart draining.
- [ ] Seed early future/terminal normalize failures and verify later eligible work progresses; retain ingest-DLQ recovery.
- [ ] Run tests against existing code and observe failure, then implement SQL eligibility before LIMIT.
- [ ] Run worker suite on PostgreSQL and record exact CI evidence.

### Task 2: Extraction and evaluation integrity

**Files:** extraction validation, hosted artifact validation, evaluation projection, related backend tests; web evaluation type/snapshot/about notice.
**Interfaces:** Existing `validate_extraction` and artifact validator; additive explicit applicability metadata.

- [ ] Reproduce acceptance of partial hosted outputs on zero/conflicting budget and reversed date documents.
- [ ] Add minimal source consistency rejection and run complete extraction regressions.
- [ ] Reproduce acceptance of fabricated reduction ratios, recompute from recorded denominators, test zero/missing usage boundaries.
- [ ] Compare recorded request identity to current identity without rewriting historical metrics; exercise stale and matching cases.
- [ ] Run evaluation tests, frontend tests/types/lint/build and relevant browser gate.

### Task 3: Privacy-safe operational diagnostics

**Files:** `apps/api/app/observability.py`, `apps/api/tests/test_observability.py`, `docs/operations.md`.
**Interfaces:** Existing `scrub_sentry_event` and `configure_error_tracking`.

- [ ] Add secret canaries to exception, top-level and thread stack frames; assert values and source context removed but diagnostic location retained.
- [ ] Run tests RED; disable SDK local capture and scrub every stack location; run GREEN.
- [ ] Verify SDK options and malformed optional stack structures without a remote DSN.

### Task 4: Explicit Slack notification contract

**Files:** webhook adapter/worker/config, channel and delivery tests, `.env.example`, `docs/notifications.md`.
**Interfaces:** `notification_webhook_formats` owner-to-`generic|slack` map; `WebhookChannel(payload_format=...)`.

- [ ] Add transport contract tests for Slack plain-text blocks, bounded text and suppressed mentions; observe RED.
- [ ] Implement format selection with existing DNS pinning, bounded timeout and durable retries.
- [ ] Accept Slack success only for HTTP 200 with bounded `ok` body; classify 429/5xx and refuse redirect/error bodies.
- [ ] Verify real worker chooses the configured format, default stays generic, and disabled/unconfigured remains non-sending.

### Task 5: Traceability and integration

**Files:** `docs/job-requirement-audit.md`, README, affected verification/limitation docs.

- [ ] Map all duties, qualifications, preferences and work-style requirements to concrete paths and evidence.
- [ ] Distinguish implemented/contract-tested/measured/missing, including billing, OCR, current LLM, large public data and GCP/AWS gaps.
- [ ] Obtain independent review and resolve material findings with regression tests.
- [ ] Run frontend/backend and real container CI on the final PR head; inspect artifacts.
- [ ] Merge the authorized changes, verify main and deployed public demo, then report improvements and remaining gaps.
