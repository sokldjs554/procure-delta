# Notification delivery

The local default stores both the notification outbox and delivered receipts in PostgreSQL.
No email or webhook is sent by default. All demo profiles and test recipients are synthetic.

`app.workers.notifications` exposes three ARQ callables:

- `reconcile_notifications(ctx)` materializes current ranking and watched changes, then commits
  immutable `notification_events`. It runs at startup and every ten minutes.
- `dispatch_pending_notifications(ctx)` publishes at most 100 due events per invocation to the
  worker queue. It runs at startup and every 30 seconds. Redis outages leave the outbox intact.
- `deliver_notification(ctx, notification_event_id)` performs one delivery attempt. Replaying it
  is safe; completed or terminal events are not resent.

Production contexts use the normal session factory and Redis pool. Tests may supply
`session_factory` and an aware `notification_now`. A `ranking_as_of` replay context suppresses
live trigger reconciliation. Explicit historical ranking jobs never call notification enqueue.

| Trigger | Current input and scope |
| --- | --- |
| `new_high_relevance` | Current eligibility and exact daily ranking inputs must be recommended; hard failures, critical unknowns and expired deadlines remain blocked. Once per owner, canonical opportunity and selected channel. |
| `watched_material_change` | Any nonempty supported current-transition field or document delta, retaining its deterministic low/medium/high impact. No-op deltas stay silent. |
| `deadline_changed` | Current-transition deadline change with medium/high impact. |
| `eligibility_changed` | Watched region, certification, capability, participation or budget conditions change, even if the company remains eligible. |
| `outcome_published` | Award/opening/contract record observed after the watch; direct watch or accepted active lifecycle path to a watched ancestor. |

Watches are forward-looking. Delta generation or link repair does not replace the source
version's original `transition_at` availability. Unknown/historical transitions are not live
watched alerts. Pending document repairs suppress older finalized deltas. Evidence-only delta
revisions share semantic dedupe keys; the first event retains its original delta and evidence.
Outcome payloads retain the outcome version and selected link IDs.

`notifications.preferences.PreferenceValues` is the typed preference contract for the product API.
`get_preferences(session, owner_id)` and `set_preferences(session, owner_id, values)` accept
the authenticated actor separately; clients cannot choose an owner in the values payload.
Defaults enable all five triggers on the local channel. Delivery rechecks preferences and the
owned watch. Removing a watch or disabling its trigger cancels queued delivery. History queries
must filter `NotificationEvent.user_id` by the authenticated owner; local receipts join by
`LocalNotificationReceipt.notification_event_id`. Operator failures contain only the event ID
and a bounded error code, never a recipient, destination URL or notification body.

External webhook delivery requires explicit operator configuration of
`NOTIFICATION_EXTERNAL_ENABLED=true` and an owner-keyed
`NOTIFICATION_WEBHOOK_DESTINATIONS` JSON mapping. Values are secret HTTPS URLs, not user-editable
profile or preference fields. Each destination is validated and DNS-pinned to a public address;
credentials in the URL, private addresses, redirects and environment proxies are rejected or
disabled. Configure endpoints only after external-message authorization. The email-compatible
`EmailChannel` produces an `EmailMessage` and stable Message-ID through the `EmailTransport`
protocol; no SMTP/provider transport is bundled. Selecting email without an installed transport
produces an honest `channel_not_configured` terminal failure.

External attempts reserve their attempt count and a 60-second lease before I/O. Each adapter
performs one request, with a connect timeout and bounded total duration. Retryable network,
429 and 5xx failures get exponential backoff plus jitter. Other 4xx and redirects are terminal.
Three attempts exhaust the budget and persist a `job_failures` DLQ record. The dispatcher uses
durable due times, so actual retries can occur after the backoff deadline at its next scan.
Cancellation or a process crash leaves a recoverable lease; recovery does not reset the budget.
Terminal rows are intentionally not automatically retried; an operator retry after a fix must
reset the event and its associated failure in one transaction (operator admin boundary).

Local receipts and sent status commit atomically with a unique event receipt key. External
delivery is at least once: a receiver may accept a request before our completion commit fails.
The same `Idempotency-Key` is reused, but external duplicate suppression requires receiver
support; a Slack/Discord-style endpoint may not provide that guarantee. No external provider
delivery was tested. Reconciliation currently scans current opportunities/profiles and locks
them for a consistent decision; large-dataset throughput is not measured or claimed.
