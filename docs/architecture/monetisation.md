# Monetisation: subscriptions, entitlements, payments, ads

No subscription, payment or advertising code existed before Phase 6b, so this is new — built provider-independent
and deliberately small. **The core football experience is free** and nothing in livescores, the match centre,
standings, news, search, favourites, notifications or community is behind a paywall.

## Free vs Premium

| Entitlement | Unlocks |
|---|---|
| `advanced_analytics` | full team analytics sections (shots, possession, passing, defence detail, discipline, xG) |
| `extended_history` | analytics windows 20/38, last-10 form, H2H last-10/all |
| `advanced_comparison` | full match comparison table, 10-match form |
| `prediction_details` | per-team expected goals, model inputs, confidence score |
| `player_analytics` | per-90, match-by-match history, trend |
| `ad_free` | no ad slots |

Plans are data (`subscription_plans.entitlements`); the two defaults (`premium_monthly` £4.99, `premium_yearly`
£39.99) bundle all six. Prices are placeholders in minor units — change them in the database.

## Enforcement

* **Server side, per request**: `get_entitlements` computes the caller's set from the database every time
  (`entitlements_for`), never from the client, a header or a cache. Endpoints either return a trimmed shape
  (analytics/comparison/prediction) or `402` with `{message, entitlement}` (longer windows).
* Caches hold the *full* object (or one object per tier); the per-user trimming happens after the cache, so a
  cancelled or upgraded user can never be served the wrong view from Redis.
* The web and mobile apps use `GET /me/entitlements` only to decide which upsell to show. Hiding a control grants
  or removes nothing; every request is re-checked. (Tests cover forged `X-Premium` / `X-Entitlements` headers.)
* An access window is computed from dates: `ACTIVE` until the paid period ends **plus `BILLING_GRACE_DAYS`** (so a
  late renewal webhook does not cut off a paying user), `PAST_DUE` the same, `CANCELLED` until the period ends,
  `EXPIRED`/`INCOMPLETE` never.

## Provider abstraction (`services/billing/providers.py`)

```
BillingProvider: create_checkout(...), cancel_subscription(id), parse_webhook(body, signature) -> BillingEvent
```

* `TestBillingProvider` — deterministic, no network; used by tests and local dev. **Refused (503) when
  `ENVIRONMENT=production`.**
* `StripeBillingProvider` — Stripe Checkout (hosted page) and webhooks over HTTPS. Written against Stripe's
  documented API but **not verified against a live Stripe account** in this repository. To use it set
  `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, `BILLING_WEBHOOK_SECRET`, and a `provider_price_id` on each plan.

Provider events are normalised to `subscription.activated | renewed | cancelled | expired | payment.failed`.
**Card data never touches this service**: checkout is on the processor's page; `payment_events.payload` stores
only ids, amounts and status (an allow-list), tested.

## Flow

1. `POST /subscription/checkout {plan_code}` (auth, 10/h) → `{url, session_id}`. Grants nothing.
2. The user pays on the processor's page. The processor calls **`POST /billing/webhook`**.
3. Webhook handling (`BillingService.handle_event`):
   * **Authenticated**: HMAC-SHA256 over `"{timestamp}.{raw body}"` with `BILLING_WEBHOOK_SECRET`, constant-time
     compare, 5-minute replay window; anything else is `400` and changes nothing.
   * **Idempotent**: the `(provider, event_id)` row is claimed with `INSERT … ON CONFLICT DO NOTHING`; a redelivery
     of an already processed/ignored event is acknowledged (`duplicate`) without re-applying anything.
   * **Retry-safe**: effects run in a savepoint; on an error the event row is kept as `FAILED` (with the error and
     an attempt counter), the endpoint answers 500 so the processor redelivers, and the retry re-applies it.
   * **Logged**: every delivery is a `payment_events` row; `payment_webhooks_total` / `…_rejected_total` metrics.
   * Unknown users/subscriptions/event types are acknowledged and recorded as `IGNORED`.
4. `GET /subscription` shows status/plan/period; `POST /subscription/cancel` cancels **at period end** (calls the
   provider first, idempotent) — Premium continues until then.
5. Failed payment → `PAST_DUE` (grace window) → access ends when the grace window passes; a later `renewed` event
   restores `ACTIVE`. `process_subscription_events` (hourly) tidies lapsed rows to `EXPIRED`.

Out-of-order delivery: events are applied in arrival order; a stale `payment.failed` after a `renewed` would
re-mark `PAST_DUE` until the next `renewed`. Stripe sends events at-least-once but generally in order; if strict
ordering matters, compare `created` timestamps (not done here).

## Operator tools

`python -m app.cli grant-entitlement user@example.com advanced_analytics --days 30` (and `revoke-entitlement`)
create/remove `entitlements` rows independent of any subscription (comps, press, promotions).

## Ads (`services/ads.py`, `GET /ads/placements`)

Abstraction only: placements `home`, `news`, `match_centre`. The API answers "may this viewer see a slot here?" —
off globally unless `ADS_ENABLED=true`; never for the `ad_free` entitlement; never on a **live** match page.
Clients reserve a clearly labelled empty container. There is no ad network, tracking pixel, identifier or
per-user targeting.

## Monetisation analytics (counters only, no personal data)

`subscription_created_total`, `…_renewed_total`, `…_cancelled_total`, `…_payment_failed_total`,
`payment_webhooks_total`, `…_rejected_total`, `premium_feature_usage_total` (a Premium view served),
`premium_feature_denied_total` (a limited/402 response). Active subscriptions are a query on `subscriptions`
(`status = ACTIVE`). Dashboard: *LivePitch — Analytics, Predictions & Premium*.

## Security notes

* Webhook secret must be long, random and different per environment; the default is dev-only.
* The endpoint reads at most 256 KB and is rate-limited per IP (120/min).
* Checkout is rate-limited; one running subscription per user (409 otherwise).
* `402` responses reveal only the feature name.
* Admin comps are operator-only (CLI), not an API.

## Mobile and the app stores

The mobile app shows Premium status, lets the user cancel, and sends them to the website to subscribe. Selling
digital subscriptions inside iOS/Android apps normally requires the platform's own billing (Apple IAP / Google
Play Billing); that is a product and legal decision, not implemented here. Entitlements are server-side, so
adding store billing later means adding a provider that emits the same normalised events.

## Limits

* Stripe adapter unverified against live Stripe; no proration, coupons, trials, tax or invoices UI, multiple
  currencies per user, or refunds handling (a refund should be sent as `subscription.expired`).
* Prices/plan copy are placeholders.
