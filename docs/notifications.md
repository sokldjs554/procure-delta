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

External delivery requires explicit operator configuration of
`NOTIFICATION_EXTERNAL_ENABLED=true`; no external channel is enabled by default.
The normal Compose stack forwards these settings to API, worker and scheduler.
`scripts/check_compose_environment.py` checks both disabled defaults and configured
JSON/SMTP values with synthetic settings; it never starts services or sends messages.

Webhook delivery uses an owner-keyed `NOTIFICATION_WEBHOOK_DESTINATIONS` JSON mapping.
Values are secret HTTPS URLs, not user-editable profile or preference fields. Each destination is
validated and DNS-pinned to a public address; credentials in the URL, private addresses, redirects
and environment proxies are rejected or disabled.

### Slack incoming webhook format

`NOTIFICATION_WEBHOOK_FORMATS` explicitly maps an owner to `"slack"` or `"generic"`.
Owners absent from this map keep the existing generic JSON contract. For example:

```dotenv
NOTIFICATION_WEBHOOK_FORMATS={"synthetic-owner":"slack"}
```

The same owner must have a secret URL in `NOTIFICATION_WEBHOOK_DESTINATIONS`, select
the `webhook` channel in preferences, and the operator must enable external delivery.
No real destination is included in the repository or enabled in the public demo.
An unknown format fails configuration instead of silently choosing another payload.

The Slack format uses a bounded `plain_text` section containing the trigger, title,
opportunity ID and notification ID. It does not forward the raw payload or evidence.
The fallback text escapes Slack control characters; Markdown, media and link unfurling
are disabled. Titles are capped at 2,000 characters to stay within the documented
3,000-character section limit. The normal DNS pinning and timeout rules still apply.
Only HTTP 200 with a bounded `ok` response is success. A 2xx error/HTML/empty/oversized
body is not success; 429/5xx retain the durable retry policy. Error bodies are not logged.

Contract tests exercise the actual adapter with a controlled HTTP transport and the
PostgreSQL outbox/worker selection path. They are **not evidence of a real Slack
workspace receiving a message**. Incoming webhooks do not promise receiver-side
idempotency; an ambiguous success may still duplicate a Slack message.

Sources checked 2026-09-26: [Slack incoming webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/),
[section block limits](https://docs.slack.dev/reference/block-kit/blocks/section-block/).

Email delivery uses `NOTIFICATION_SMTP_HOST`, optional SMTP credentials, one operator-owned
`NOTIFICATION_EMAIL_SENDER`, and an owner-keyed `NOTIFICATION_EMAIL_RECIPIENTS` mapping.
Empty optional SMTP username/password settings are treated as absent credentials.
STARTTLS is enabled by default. `EmailChannel` emits a stable Message-ID from the notification
dedupe key and `SmtpTransport` performs one bounded SMTP attempt. CI starts a loopback SMTP
receiver and verifies a real TCP delivery from the durable outbox path through the worker to the
received message. This is transport integration evidence, not proof of delivery through a public
email provider. Selecting email without complete operator configuration still produces an honest
`channel_not_configured` terminal failure.

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
The same webhook `Idempotency-Key` or email Message-ID is reused, but external duplicate
suppression requires receiver/provider support. A Slack/Discord-style endpoint or SMTP provider
may still accept the same message twice after an ambiguous success. Loopback SMTP is tested;
no public email or webhook provider delivery is claimed. Reconciliation currently scans current opportunities/profiles and locks
them for a consistent decision; large-dataset throughput is not measured or claimed.
