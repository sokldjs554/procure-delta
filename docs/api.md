# Product API and synthetic demo sessions

The API is versioned under `/api/v1`. `/openapi.json` is the typed contract; decimal amounts and
scores serialize as strings, UUIDs as strings, and timestamps include a timezone. DTOs reject
unknown request fields. Flexible pipeline provenance and version payloads remain JSON values.
This is **non-production synthetic demo authentication**, not a production identity platform.

## Local browser and server boundary

Run the documented Compose stack. The browser uses `http://localhost:8000`; Next.js server
requests use `API_INTERNAL_URL=http://api:8000`. Never put the internal hostname or operator
secret in `NEXT_PUBLIC_*` variables. Browser requests use `credentials: "include"`; a Next.js
same-origin proxy must forward the session cookie and `X-CSRF-Token`, and forward `Set-Cookie`
back to the browser. Do not cache personalized API responses. Server-side requests must carry
the incoming user's cookie rather than sharing a process-wide cookie jar.

`CORS_ORIGINS` is a JSON array with `http://localhost:3000` as the local default. Credentials
are enabled only for those explicit origins. Writes reject a supplied Origin outside this
list and require the session CSRF token. Tools without an Origin still need the token. The
demo-login bootstrap accepts JSON and checks a supplied Origin; it cannot select an owner.
Use a same-origin reverse proxy and `SESSION_COOKIE_SECURE=true` with HTTPS in hosted demos.
The localhost HTTP default is `false`; the cookie remains HttpOnly, SameSite=Lax, Path=/.

## Login and roles

`POST /api/v1/auth/demo-login`, JSON `{}`, creates a new server-assigned synthetic owner and
synthetic company profile. A valid existing user session reuses its owner. Public callers
cannot impersonate the separately seeded `synthetic-demo-owner`; `X-Demo-Owner` has no effect.
No owner or role field is accepted in the login body.

An operator sets `DEMO_OPERATOR_SECRET` in the ignored local `.env` or deployment secret
configuration, then posts `{"operator_secret":"<configured secret>"}`. An empty/unset secret
disables operator login. It is intentionally not shipped as a public default credential.
`DEMO_AUTH_ENABLED=false` disables new demo logins. This is not a production login mechanism.

Both successful login modes return:

```json
{
  "owner_id": "synthetic-session-<server-generated identifier>",
  "role": "user",
  "csrf_token": "<session CSRF token>",
  "synthetic_demo": true
}
```

Operator responses have `role: "operator"`. The response sets `procure_delta_session`, an
opaque random HttpOnly cookie; Redis stores the actor under a hash of the token. Sessions
expire after 24 hours by default (`SESSION_TTL_SECONDS`, maximum 24 hours). Keep the CSRF token
in browser memory and send it in `X-CSRF-Token` on POST/PATCH/PUT/DELETE. Login is limited to
10 attempts per minute per directly connected client address; do not blindly trust forwarded
addresses. A trusted reverse proxy must provide its own public edge limits.

`GET /api/v1/auth/session` returns the same actor/CSRF shape. `POST /api/v1/auth/logout` requires
CSRF, revokes Redis state, deletes the cookie and returns 204. Missing/expired/forged sessions
return 401; a user calling an admin route receives 403. Role changes create a fresh owner and
rotate/revoke the prior session. Losing a demo cookie loses access to that synthetic owner;
there is no account recovery, password database, or production account lifecycle.

## User resources

| Method and path | Contract |
| --- | --- |
| `GET /company-profile` | Authenticated owner's profile; login creates it. |
| `POST /company-profile` | Creates only if absent; otherwise 409. |
| `PATCH /company-profile` | Partial updates; merged bounds/currency/list validation; ownership is session-derived and `synthetic_demo` must stay true. |
| `GET /opportunities` | `{items, next_cursor}`; bounded keyset feed. |
| `GET /opportunities/{id}` | Summary, current eligibility/ranking, versions, active and historical lifecycle decisions, delta history, documents and current extraction state. |
| `GET /opportunities/{id}/timeline` | Connected active link IDs and opportunity IDs; retracted decisions are separate and never expand the active chain. |
| `GET /opportunities/{id}/deltas` | Retained comparisons with `applicable_now`, plus `current_inputs_ready`. |
| `GET /opportunities/{id}/eligibility` | Current matching decision or null while unavailable. |
| `GET /opportunities/{id}/ranking` | Current ranking decision or null while unavailable. |
| `GET /opportunities/{id}/evidence` | Current configured extraction identity and grounded claims. |
| `GET /opportunities/{id}/versions/{version_id}/evidence` | Applicable extraction for the specified owned version. |
| `GET /opportunities/{id}/versions/{version_id}/extractions` | All retained extraction snapshots, untrusted proposal, validation/conflicts and `applicable_now`. |
| `GET /opportunities/{id}/versions/{version_id}/documents` | Version document descriptors and parse quality. |
| `GET /documents/{id}/original` | Checksum-verified content-addressed bytes; forced attachment/octet-stream with a generated safe filename. Never fetches a caller-supplied URL. |
| `POST /opportunities/{id}/watch` | Idempotent owned watch; `{opportunity_id, watched:true}`. |
| `DELETE /opportunities/{id}/watch` | Idempotent owned removal; 204. |
| `GET /watchlist` | Owned `{items, next_cursor}`. |
| `GET /notifications` | Owned `{items, next_cursor}`, including receipt ID/time joined to the event. |
| `GET /notifications/preferences` | Typed owner preferences. |
| `PUT /notifications/preferences` | Replaces preferences using `PreferenceValues`; unspecified fields get documented defaults. |

Feed parameters are `q`, `lifecycle_stage`, `category`, `buyer`, `status`, `amount_min`,
`amount_max`, `deadline_from`, `deadline_to`, `eligible_only`, `changed_since`, `limit` and
`cursor`. Limits are 1–100, default 20; dates require a timezone and ranges are inclusive.
`q` searches title/buyer case-insensitively; buyer is a literal substring; `%`/`_` are escaped.
Stage/category/status are exact matches. Amount filters use normalized amounts; clients
should interpret their displayed currency. Deadline filters use normalized closing dates.
`changed_since` uses observed current-version transitions, excluding historical-only arrivals.

The main cursor carries publication time, UUID and a filter/owner fingerprint, ordered by
publication descending then UUID descending. Null publication dates sort as the Unix epoch.
Do not reuse a cursor after changing filters. `eligible_only` means current eligibility without
warnings, not a guarantee of recommendation. It examines at most 1,000 candidates per request;
a short/empty page with `next_cursor` is a continuation, not the end. Stop only at a null cursor.
Watches, notifications and failures use UUID keysets; these lists do not claim chronological
UUID ordering. Large-dataset API latency and materialization throughput have not been measured.

Current decisions reuse the authoritative profile/opportunity/extractor fingerprints, with a
UTC daily ranking bucket whose deadline state comes from the ranking service. Profile edits
therefore affect the next bounded feed/detail read immediately. They do not trigger external
LLM calls. Unknown hard conditions remain eligibility warnings and block recommendation.
`decision_status` distinguishes `ready`, `profile_required`, `missing_version`,
`documents_pending` and `future_version`. Pending document repair withholds prior matching
decisions. Reads can materialize immutable matching/delta revisions but never replay historical
notifications or send messages.

Native parse `status: trusted` describes text quality only. Structured extraction separately
reports `pending`, `documents_pending`, `no_suitable_pages`, `validated`, `rejected` or
`untrusted`. Only the exact configured extractor and current document fingerprint can supply
current grounded claims. Conflicting upstream/attachment fields are withheld and exposed in
`conflicts`. Evidence includes checksum, page number and quote; document descriptors supply
safe API original links. Historical proposals remain explicitly separate from current trust.
Delta reads prepare current input snapshots and materialize the exact applicable fingerprint
before marking any retained comparison current. Pending repairs leave prior rows inspectable
but not applicable.

Flexible response JSON is a public projection, not a verbatim upstream/provider payload.
Known business fields, evidence IDs/checksums/page references and pipeline quality/explanation
fields are allowlisted recursively. Transport locations, headers, credentials and unknown nested
metadata are excluded, including metadata inside arrays and copied notification history. Where
stored attachment identity resolves unambiguously, manifests and delta values/evidence carry
`attachment_id`, `sha256` and a safe relative `original_url` instead of the remote location.
Actual evidence `quote` and page `text` values remain verbatim, including literal URLs that are
part of document content. Stored source/version/delta/notification JSON and fingerprints are
unchanged. Historical proposals use the same projection. Validation exceptions that may include
rejected input become `schema_validation_failed`/`validation_failed`; known grounding diagnostics
remain visible.

Preferences use `enabled`, `channels` (`local`, `webhook`, `email`) and the five triggers in
[notifications.md](notifications.md). No owner/destination field is accepted. The local channel
is the default; choosing an unconfigured external channel yields an honest delivery failure.
This API does not configure destinations or send external messages itself.

## Operator and runtime resources

| Method and path | Contract |
| --- | --- |
| `GET /health/live` | Process liveness only; no upstream dependency calls. |
| `GET /health/ready` | 200 only when PostgreSQL, migration head, Redis, worker/scheduler heartbeats, writable storage and extractor configuration pass; otherwise 503 with booleans only. |
| `GET /api/v1/release` | Package version, configured revision, extraction mode and non-production authentication label; no credentials/endpoints. |
| `GET /api/v1/admin/pipeline` | UTC-day ingest aggregates, stored parser/OCR/extraction counts, unresolved retry/DLQ counts, actual Redis queue depths and ARQ heartbeat activity. |
| `GET /api/v1/admin/sources` | Source identity, enabled/poll interval and last success/failure; base URLs/credentials are excluded. |
| `GET /api/v1/admin/failures` | Pending failure keyset, optional `dead_lettered`; safe error code only, no raw messages/payloads. |
| `POST /api/v1/admin/failures/{id}/retry` | Operator+CSRF; terminal supported failure reset with audit; 202 `{failure_id,status:"retry_pending",queue_published}`. |

Heartbeat activity counts are cumulative since each ARQ process started, not a throughput rate.
Absent/unparseable heartbeats produce null activity, not invented zero counts. Workers refresh
heartbeats every 30 seconds. Parser/extraction groups include retained historical versions;
they are operational processing totals, not counts of current opportunities. Schema validation
failures include structured rejection/grounding failures. A resolved `JobFailure` has attempts
zero, no next retry and no terminal flag, even though its historical error class remains.
Successful notification delivery resets the failure's attempts; the event's delivery attempt
count remains its actual attempts for that delivery budget.

Manual retry is limited to five attempts per minute per authenticated operator and accepts
only terminal failures. Supported jobs are poll, ingest, normalization, document parsing,
extraction, lifecycle linkage, delta computation and notification delivery. Target state and
`JobFailure` reset atomically, using worker-compatible lock order; an audit preserves the actor.
Notification retry preserves event/dedupe identity, grants a new bounded budget and rejects
already delivered receipts. Durable due state is committed before best-effort Redis publication;
the existing reconcilers recover it if publication fails. Unsupported/missing/stale inputs return
409. Resolved entries and the two intentionally retained legacy-invalid development raw records
are not silently removed to make the dashboard look healthy.

Readiness does not poll public sources or require optional source credentials. Existing normalized
reads remain available during an upstream outage. Redis outages can prevent session validation
and make readiness fail; liveness remains independent. Demo sessions, lazy matching scans and
unbounded per-opportunity history are portfolio-scale choices; production identity, retention,
large-dataset tuning and distributed rate-limit edge configuration are outside this task.
