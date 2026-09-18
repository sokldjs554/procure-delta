# Deterministic Delta Engine

`app.delta.engine.compute_delta(before, after)` accepts two `DeltaSnapshot` inputs and
returns an `OpportunityDelta`. Inputs carry the immutable normalized version, its actual
raw record, the separately persisted attachment manifest, and (when available) the
validated, nonconflicting extraction view. No paid model is required.

The `delta-v1` rules compare decimal budgets with their currency as one claim, UTC
deadlines, sorted restriction/requirement sets, participation-clause text, contract
periods, and attachment source URLs/checksums. Each change contains machine-readable
`before` and `after` values and separate evidence pointers. Raw pointers identify the
record, payload checksum and JSON field; attachment claims retain checksum, page and
quote; attachment changes identify their persisted manifest rows. A default KRW currency
is labeled as a normalizer default, not an upstream quotation.

## Severity policy

| Change | Level | Reason codes |
| --- | --- | --- |
| Budget amount/currency | medium | `budget_increased`, `budget_decreased`, `budget_currency_changed` |
| Earlier deadline | high | `deadline_earlier` |
| Later deadline | medium | `deadline_later` |
| Region restriction added/changed | high | `region_restriction_added`, `region_restriction_changed` |
| Region restriction removed | medium | `region_restriction_removed` |
| Certification/capability added | high | `certification_added`, `capability_added` |
| Certification/capability removed | medium | `certification_removed`, `capability_removed` |
| Participation clause text | high | `material_clause_changed` |
| Contract period | medium | `contract_period_changed` |
| Attachment added | low | `attachment_added` |
| Attachment removed/replaced | medium | `attachment_removed`, `attachment_replaced` |
| Claim becomes known/unknown | medium | `<field>_became_known`, `<field>_became_unknown` |
| No material changes | low | empty reason list |

The maximum level wins; reason codes are sorted and deduplicated. The rules do not use
the current time or a language model. Missing, failed, rejected or withheld claims are
unknown (`null`), not evidence that a requirement or deadline was removed. An explicit
upstream empty requirement list can establish removal. Free-text comparison is exact
after normalization, not a claim of general legal/semantic interpretation.

`explain_delta` passes a defensive copy of the deterministic result to an optional prose
generator. It returns a separate string and never changes stored severity or machine values.

## Chronology and revisions

Version numbers retain append-only observation order. Normalization captures
`previous_current_version_id`, `transition_kind`, and `transition_at` under the existing
graph and canonical-key locks. Equivalent later observations can advance the upstream
watermark without creating a version. Consequently a late historical version is never
assumed to be the previous current state.

Current transitions compare their recorded previous current version to the new current
version. Historical versions compare to the previous observation and are labeled
`historical`. Pre-migration versions retain `unknown` transition provenance; their
comparisons are `legacy_unknown` and never notification inputs. Migration does not invent
past decisions or rewrite normalized snapshots.

Each finalized delta is an immutable revision, unique by version pair, ruleset and input
fingerprint. Its provenance records observation numbers, upstream times, decision time,
attachment rows/checksums, extraction identity/status and processing gaps. A deliberate
repair or different configured extraction result can append a revision. Existing change
content remains intact.

`latest_applicable_deltas(session, opportunity_id)` returns the newest finalized
`delta-v1` revision of the current transition whose target is still the opportunity's
current version. Historical, legacy-unknown and superseded targets are excluded.
Downstream notifications must use this selector and deduplicate on the version
pair plus deterministic reason codes and before/after values. Evidence-only enrichment
must not resend an already delivered semantic change merely because its delta ID changed.

## Durable processing

`compute_opportunity_delta(ctx, to_version_id)` and `reconcile_pending_deltas(ctx)` are
registered ARQ worker functions. Reconciliation runs at scheduler startup and every ten
minutes, discovering work from PostgreSQL so lost Redis jobs can be recovered. Concurrent
jobs serialize on the opportunity; pair/input uniqueness is also enforced in PostgreSQL.
Failures use bounded durable retry/dead-letter state.

Both snapshots must complete document discovery/processing before finalization. Explicit
no-attachment discovery is terminal. Suitable pages must have the configured extraction
result (`validated` or `rejected`), or a terminal failure for that exact extraction key.
No suitable pages is an explicit terminal outcome. Unsupported formats, parse/OCR failure,
rejected/conflicting claims and dead-lettered document/extraction jobs remain visible gaps.
Transient failures keep the gate closed. Reprocessing closes it until completion again.
Each document run owns a persisted generation token. After native-parse recovery commits
release row locks, only that generation may complete processing or record a terminal gap;
an older OCR worker or failure replay cannot finish a newer repair. Generation tokens and
processing timestamps are excluded from delta fingerprints, so unchanged pipeline replay
does not create another revision.
Retry and dead-letter gates apply only to the current generation. A deliberate newer
repair starts its own retry budget; a stale worker cannot overwrite that budget. Ordinary
retries preserve their generation and accumulated attempts, including discovery failures
carried into the first staged document generation, so retries remain bounded.
Unknown manifests never establish attachment absence, and missing checksums never prove
content replacement. Raw-supported changes can still finalize alongside terminal gaps.

The local synthetic amendment revisions demonstrate budget growth, a later deadline,
and newly required Seoul participation and ISO 27001 certification. Their effective
times continue to use real ingestion observation time; no future upstream timestamp is
fabricated to change current-version selection.
