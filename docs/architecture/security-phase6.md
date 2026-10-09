# Phase 6 security and privacy review

Scope: everything added in 6a and 6b. Method: reading each new endpoint and service against the checklist below,
then writing a test for every control that can be tested. "Test" names refer to `apps/api/tests/`.

## Authorization and entitlements

| Risk | Control | Evidence |
|---|---|---|
| Premium data served to a free user | Entitlements computed from the database on every request (`entitlements_for`), never from the client; responses shaped after the cache; 402 for over-limit windows | `test_analytics_api` (basic vs full, cache not shared across users, 402s), `test_billing::test_entitlements_are_users_own_and_never_taken_from_the_client` (forged headers/query ignored) |
| Stale premium after cancellation | Entitlements are never cached; access is a function of dates (`subscription_grants_access`) | `test_cancel_keeps_premium_until_the_period_ends`, `test_renewal_extends_and_payment_failure_…` |
| Frontend-only hiding | Web and mobile use `/me/entitlements` for presentation only; every protected call is re-checked | the same tests plus the Docker run (402 for a free user's `window=20`) |
| Role escalation | Roles are granted only with the operator CLI; moderator/admin dependencies check the role from the DB row; admins cannot suspend admins or themselves | `test_editorial_workflow` / `test_phase6b_social::test_only_admins_suspend…` |
| IDOR | Subscription, insights and entitlements always use the authenticated user's id; no endpoint takes a user id for those; profile reports/suspension are role-gated | tests above |

## Payments and webhooks

* Signature: HMAC-SHA256 over `timestamp.body`, constant-time compare, 5-minute window (replay), 256 KB cap, 120/min/IP.
  Unsigned, forged, tampered and stale deliveries return 400 and change nothing (`test_unsigned_forged_tampered_and_stale…`).
* Idempotent and retry-safe (`payment_events` unique key; FAILED rows retried): `test_activation_grants_entitlements_and_is_idempotent`,
  `test_a_failed_event_is_recorded_then_retried_successfully`.
* A webhook is the **only** way a plan activates; checkout grants nothing (`test_checkout_requires_login_and_grants_nothing`).
* No card data: hosted checkout; the stored event payload is an allow-list of ids/amounts (`test_the_audit_row_stores_ids_and_amounts_not_card_data`).
* Production guards: the `test` provider is refused when `ENVIRONMENT=production`; the Stripe provider is refused there with the
  default/short webhook secret (`test_production_refuses_the_dev_secret_and_the_test_provider`).
* Residual: the Stripe adapter is untested against a live account; webhook events are applied in arrival order (see monetisation.md).

## Abuse, spam and rate limiting

Comments (5/min, 40/h, links/age/duplicate rules, auto-hide at 3 reports), reactions (30/min), votes (20/min), uploads (20/min,
200/day), checkout (10/h), profile reports (10/h), webhook (120/min), analytics/comparison (240/min/IP, the only unauthenticated
endpoints that run an aggregate on a cache miss), search (existing). Counters are in Redis; the limiter fails open on a Redis
outage (documented behaviour) — durable limits for comments are also enforced by database uniqueness (one reaction/vote per user).
Test: `test_analytics_endpoints_are_rate_limited_per_client` and the Phase 6a community tests.

## Injection and XSS

* SQL: SQLAlchemy parameters everywhere; no string-built SQL in new code. Enum/identifier inputs are validated (`window`, `scope`).
* Comments, bios, insight text, report reasons are plain text; React escapes on web and mobile; nothing new uses
  `dangerouslySetInnerHTML`. Article HTML still passes the allow-list sanitizer. Test: mobile `renders comment bodies as plain text`.
* Media: content judged by bytes, re-encoded, size/pixel limits, server-generated keys, sandboxed + `nosniff` responses.
* Real-time payloads are ids/counts only.

## Authentication and enumeration

* Suspended accounts: all authenticated requests and token refreshes fail, sessions are revoked, and sign-in says "suspended"
  only after the password is verified (`test_only_admins_suspend_and_suspension_locks_the_account_out_everywhere`).
* Private and missing profiles are indistinguishable (404); a private profile cannot be reported.
* Cookie auth is `httpOnly; SameSite=Lax`. State-changing endpoints reached with cookies rely on SameSite=Lax plus the CORS
  allow-list (pre-existing design); mobile uses bearer tokens.

## Privacy and data collection

| Data | Why | Retention | Optional? |
|---|---|---|---|
| Comments, reactions, poll votes | the feature; one-per-user enforcement | until the user/content is deleted (cascade) | participation is optional; public profile visibility is opt-in |
| Report rows (reporter, reason) | moderation | until resolved/deleted with the user | — |
| Subscription + payment events | entitlement, idempotency, audit | kept for accounting/audit; ids and amounts only | — |
| Predictions, insights, analytics | derived from public football data | regenerated; predictions kept for evaluation | — |
| Premium-use and paywall counters | product health | aggregate counters, no user id | — |
| Logs | operations | per deployment; ids not bodies; emails/tokens redacted | — |

Not collected: location, device fingerprints, ad identifiers, per-user reading history (views are anonymised counters), card data.
Ads: no tracking, no per-user targeting; an empty labelled slot only.

## Dependencies

`npm audit --omit=dev` reports pre-existing transitive findings (web: 10 — 9 high, 1 critical; mobile: 68) in packages this phase did not
add; they have **not** been triaged or fixed here. No `pip-audit` run was available. This should be a Phase 7 task.

## Known gaps

No antivirus/perceptual scanning of uploads, no CAPTCHA on registration/commenting, no Alertmanager wiring, `/metrics` is
unauthenticated (keep it internal), no automated browser security testing.
