# Hosted extraction credit integration

## Scope and accounting policy

The opt-in extraction worker charges a configured **pipeline budget account**.
Collected procurement documents are shared data, so there is no inferred customer
payer. `EXTRACTION_CREDITS_ENABLED=true` requires hosted mode and an explicit
`EXTRACTION_CREDIT_ACCOUNT`. `EXTRACTION_CREDIT_UNITS` is a positive integer per
logical extraction (default 1). This is an internal service unit, not USD, a
provider invoice, token billing, a subscription, or a limit on HTTP retry costs.
The existing hosted adapter may make up to three HTTP attempts per extraction.
Local OCR and deterministic extraction are not charged by this integration.

## Transaction and recovery contract

1. Lock the opportunity version; rebuild its document identity and check for an
   existing result. Cached, stale and empty work consumes no credits or calls.
2. Before a new provider call, reserve units in the existing PostgreSQL ledger
   and commit that reservation. Insufficient balance stops before network I/O.
3. Re-lock and recheck the input after this transaction boundary. A duplicate
   finding a recent reservation defers without recording a failure. The owner
   must re-lock within 120 seconds to start a call; an older hold requires review.
   If the input changed before calling the provider, refund without a call.
4. Persist the schema/grounding outcome and commit the reserved units in the
   same transaction. A rejected provider answer is still completed, charged work.
5. If a call or result persistence raises, or the worker is cancelled/crashes,
   the durable reservation remains held. A repeated job cannot call again or
   infer a refund from elapsed time. Caught failures become terminal credit-review
   failures immediately. After a cancellation/crash, repeats defer while the hold
   is younger than 120 seconds, then reconciliation exposes a terminal review
   failure. Age never authorizes a new call or an automatic refund.

The fence is keyed by version plus extraction identity, independently of the
configured account. Changing the account, units, or disabling credit mode does
not authorize replay of an unresolved or manually settled attempt. A new document
or extractor identity is different work. Existing unbilled results are not
retroactively charged. Operator reconciliation cannot recover a lost model answer.

## Verification

Real PostgreSQL integration tests cover persisted reservation before provider I/O,
atomic result/debit, cached and concurrent execution, insufficient balance,
rejected output, provider timeout, cancellation, persistence failure, changed
input refund, the reservation commit/re-lock race, configuration changes,
active-call/operator locking, and conflicting operator decisions. External
provider responses are controlled in these tests; no paid call is made by CI.

## Deployment boundary

Default configuration stays disabled. Operators must provision credits and set
the same policy on API, worker and scheduler before opting in. No free balance is
created at startup. The account is set by trusted deployment configuration, never
by an unauthenticated request or a guessed company profile.

This work does not implement a payment processor, recurring subscriptions,
customer-facing purchase UI, or per-customer billing of shared ingestion.

## Operator commands

Run these only in the trusted backend environment with the intended database.
Funding is an internal budget allocation, not an assertion of payment received.
Reuse the same request ID for retries of one allocation.

```sh
python -m app.ops.extraction_credits status --account pipeline-budget
python -m app.ops.extraction_credits grant --account pipeline-budget --units 100 --request-id initial-budget-1
```

Then set `EXTRACTION_MODE=hosted`, the existing provider settings, and:

```dotenv
EXTRACTION_CREDITS_ENABLED=true
EXTRACTION_CREDIT_ACCOUNT=pipeline-budget
EXTRACTION_CREDIT_UNITS=1
```

For an unresolved hold, first investigate the provider/worker records. `commit`
confirms consumption; `refund` confirms that the internal units should be returned.
Neither decision asserts a provider refund or recovers the missing response.

```sh
python -m app.ops.extraction_credits resolve --account pipeline-budget --reservation extraction:REPLACE_WITH_HOLD_KEY --decision refund
```

Resolution refuses holds younger than 120 seconds and locks the same version as
the worker, so it cannot settle during a locked active call. This delay is a
manual-operation guard, not proof of provider outcome. Repeating a decision is
idempotent; switching an already settled decision is rejected. Manual settlement
leaves the original attempt fenced; retrying the DLQ entry cannot call it again.
The CLI displays at most 100 holds and never prints provider responses or secrets.
