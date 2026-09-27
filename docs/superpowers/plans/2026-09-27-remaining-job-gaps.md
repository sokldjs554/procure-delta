# Implementation plan: remaining job gaps

**Scope:** implement the adjacent specification under the user's existing
authorization to fix and finish the job audit gaps.

1. Add failing HTTP/KONEPS contracts and PostgreSQL inbox query-count tests.
   Observe real failures, then implement bounded retry classification and batch
   summaries. Recheck existing filtering/cursor/owner behavior.
2. Add sandbox signature/parser contracts first, then models/migration, isolated
   account kind, atomic invoice application service, disabled webhook route and
   explicit operator CLI. Cover real PostgreSQL concurrency, rollback, conflict,
   migration, isolation and delivery-order cases.
3. Diagnose and remeasure original OCR assets in a separate fixed runtime. Add
   tests for candidate error classification, implement the minimal fix and retain
   truthful frozen-corpus quality results.
4. Wire settings through Compose and configuration checks. Document operator
   replay instructions, supported invoice scope, evidence provenance and all
   remaining external-validation gaps. Update public demo copy where relevant.
5. Run focused local contracts, typecheck/lint, actual PostgreSQL and container
   CI, frontend/browser checks. Resolve concrete failures and obtain independent
   review. Record final measurements and test references.
6. Merge the reviewed green tree, verify Render publishes that commit, and check
   the public routes/assets. Report improvements and remaining measured gaps.

Ownership: source retry agent owns source HTTP/KONEPS and worker transient
classification; inbox agent owns opportunity summaries and performance tests;
OCR agent owns candidate diagnostics and OCR evidence; billing agent owns the
new billing backend, credit isolation, settings, route and tests. Root owns
Compose/release wiring, audit/public copy, integration and deployment.
