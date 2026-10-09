# Payment webhook failures and entitlement problems

**Symptoms.** `PaymentWebhookProcessingFailing`, `WebhookSignatureRejections`, `PaymentFailures`; a user says "I paid but I'm not Premium", or "I cancelled but I'm still billed".

**What is true by design.** The only way a subscription becomes active is a *verified webhook*. The checkout response grants nothing, and there is no client-side
"payment succeeded" call. Entitlements are computed from the database on every request, so fixing the subscription row fixes access immediately.

## Diagnose

1. **Is the webhook arriving?** `payment_webhooks_total` rising; `payment_webhooks_rejected_total` (bad signature or stale timestamp); `…_failed_total` (verified but processing raised); `…_stale_total` (an older event arrived after a newer one and was ignored — normal).
2. **Signature rejections** → the signing secret differs from the processor's (`BILLING_WEBHOOK_SECRET`), the server clock is wrong (the replay window is 5 minutes — check `date -u`), or something is probing the endpoint (the 120/min rate limit applies).
3. **Processing failures** → `GET /api/v1/admin/users/{id}` (subscriptions, entitlements) and the `payment_events` row for the event id: `status=FAILED`, `error`, `attempts`. **Failed events are retried when the processor redelivers** (Stripe retries for days), and processing is idempotent — duplicates are acknowledged without effect.
4. **A user's state looks wrong** → compare the `payment_events` timeline (events are ordered by the processor's timestamp, not arrival): `docker compose … exec postgres psql -U football -c "select event_type, status, received_at, error from payment_events where payload->'object'->>'user_id' = '<id>' order by received_at"`.
5. **Provider unreachable at checkout** → `POST /subscription/checkout` returns 502/503 and nothing is created; the user can retry. Check `STRIPE_SECRET_KEY` and outbound connectivity.

## Fix

| Cause | Action |
|---|---|
| Wrong/rotated webhook secret | set `BILLING_WEBHOOK_SECRET` to the processor's endpoint secret, redeploy, then **replay** the failed deliveries from the processor's dashboard |
| Processing bug | fix and deploy; the processor's retries (or a manual resend) apply the events; nothing is lost because the raw event ids are stored |
| Subscription missing after a confirmed payment | resend the event from the processor; if impossible, grant a temporary entitlement *by hand and audit it*: `python -m app.cli grant-entitlement user@example.com advanced_analytics --days 30` (recorded in the audit log), and reconcile later |
| Processor outage | wait; webhooks queue on their side |
| Account deletion blocked by billing | the processor could not cancel (502) — retry later; nothing was erased |

## Verify

`payment_webhooks_failed_total` flat; the affected `payment_events` rows `PROCESSED`; `GET /api/v1/me/entitlements` as the user (admin impersonation is not provided) shows the right set.
