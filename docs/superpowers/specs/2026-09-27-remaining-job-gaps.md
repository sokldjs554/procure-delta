# Remaining job requirement improvements

The user requested the maximum practical correction of the gaps found in the
2026-09-26 job audit. This work extends that approved scope without external
charges, a new merchant account, paid infrastructure, or unsupported claims of
production operation.

## Outcomes

1. Source HTTP retries respect Retry-After within an overall deadline; KONEPS
   application errors distinguish transient service failures from configuration
   and quota failures without exposing response text or credentials.
   A follow-up review found that cron/ARQ could otherwise retry before a delay
   longer than the request deadline. Preserve a safe UTC retry-not-before value
   into durable source-poll retry state, honor it on every poll entry, and use a
   connection-scoped per-source advisory lock for concurrent pollers. The same
   checked-out connection must release the lock on every exit. Honor server
   delays up to 24 hours; longer or overflowing delays require operator review
   rather than being shortened. Other worker stages retain their current policy.
2. Inbox watch and latest-transition metadata use batch queries. A normal page
   does not compute eligibility/ranking for its lookahead row. Existing ownership,
   eligibility filtering, stable pagination, and detail behavior remain correct.
3. Actual public OCR inputs are rechecked. Candidate failures expose bounded,
   allowlisted diagnostics. Scores change only after the same frozen evidence
   passes; unavailable documents and semantic extraction failures stay explicit.
4. Add a disabled-by-default Stripe sandbox webhook contract connected atomically
   to an isolated PostgreSQL credit ledger. This is a local, synthetic signed
   webhook integration, not a claim of actual Stripe receipt, checkout, cash
   payment, subscription operation, or production customer identity.

## Sandbox billing design

- Pin snapshot events to Stripe API `2025-03-31.basil`, whose invoice parent and
  line pricing structures are documented. Reject live, Connect/context, thin,
  unknown-version, and malformed inputs. No outgoing provider API exists.
- `POST /api/v1/billing/stripe` is disabled unless an explicit sandbox scope and
  SecretStr webhook signing secret are configured. Return 404 when disabled.
  Bound request bytes (256 KiB), signature length, IDs, integers and collections.
- Verify raw bytes using timestamped HMAC-SHA256, constant-time comparison and a
  300-second past/future tolerance before JSON decoding. Support secret rotation
  signatures via multiple v1 entries, reject ambiguous timestamps and duplicate
  JSON keys. Responses/logs never echo payloads, signatures or secrets.
- Operator-only CLI creates immutable customer-to-account and price-to-policy
  bindings. No customer metadata, demo session, or request parameter can choose
  the ledger owner, credit amount, or an existing internal budget account.
  Price currency, exact minor-unit amount, quantity=1 and credit units are
  explicit operator inputs; the application supplies no invented product price.
- Existing credit accounts become `internal_budget`; new mapped accounts are
  `billing_sandbox`. Account kind and bindings are immutable at the database
  boundary. Normal grant/reserve/settlement rejects sandbox accounts; the billing
  grant explicitly requires the sandbox kind. A sandbox balance cannot fund a
  hosted LLM request, including through an environment variable misconfiguration.
- Persist only allowlisted event facts plus a digest, never raw personal data.
  Event uniqueness is `(scope,event_id)`; credit application uniqueness is
  `(scope,invoice_id)` globally across accounts. Repeated different event IDs for
  one invoice cannot grant twice. Conflicting replays fail safely. Preserve the
  applied policy/account/units/ledger reference snapshot across replays.
- Only `invoice.paid`, with paid status, positive exact configured amount, zero
  remaining amount, subscription_create/cycle reason, a complete single line,
  quantity 1, no proration, matching subscription IDs, correct currency/price and
  valid period, can grant credits. Unsupported discounts/taxes/adjustments or
  incomplete line sets require review and do not grant. Type checks reject bools
  as integers and protect database integer bounds.
- Invoice application and ledger grant commit in one transaction. Lock ordering
  and unique constraints cover concurrent deliveries and rollback. A response
  lost after commit remains safe to retry.
- Failed invoice and subscription lifecycle events are observations only.
  Delivery order and second-resolution `event.created` do not define current
  entitlement. Failed→paid is allowed; paid→failed does not undo a grant.
  Refunds, disputes, prorations, cancellation policy and cash reconciliation are
  unsupported and explicitly reported for review; reserve refunds are not cash
  refunds. There is no subscription management or billing customer UI.

## Verification and evidence

Use controlled HTTP transports and DB-free contracts locally, then actual
PostgreSQL CI for migrations, query counts, atomicity, concurrency and all credit
regressions. Test signature/privacy/mode/bounds and immutable mapping attacks.
Run the existing container, browser, frontend, typing and lint gates on the final
tree. Independently review the integrated change before merging. Update the job
audit and public limitations using observed results, with synthetic versus real
external evidence distinguished throughout.

Primary references: [Stripe webhooks](https://docs.stripe.com/webhooks),
[Basil invoices](https://docs.stripe.com/api/invoices/object?api-version=2025-03-31.basil),
[Basil lines](https://docs.stripe.com/api/invoice-line-item/object?api-version=2025-03-31.basil),
[KONEPS service](https://www.data.go.kr/data/15129394/openapi.do),
[HTTP Retry-After](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after).
