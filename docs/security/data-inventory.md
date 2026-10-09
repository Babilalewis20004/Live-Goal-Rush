# Data inventory, retention, access and deletion

What the platform stores about people, why, for how long, who can read it, and what happens when someone asks to be
forgotten. Reflects the schema at migration `c7e0a3f19d42` (Phase 7). This is an engineering inventory, not legal advice:
confirm retention periods and the legal basis for each category with counsel before launch (checklist item).

| Data | Where | Purpose | Retention | Who can access | Deleted on account erasure? |
|---|---|---|---|---|---|
| **Account**: email, display name, bio, profile visibility, role, created date | `users` | sign-in, identity, personalisation | until erasure | the user; admins (`/admin/users`); never other users unless the profile is public (then name/bio only) | email, name, bio, password hash are **scrubbed**; the row stays as an anonymous tombstone (`deleted-<id>@deleted.invalid`) |
| **Authentication**: password hash (bcrypt), refresh-token hashes (+ IP, user agent), password-reset token hashes | `users`, `refresh_tokens`, `password_reset_tokens` | authentication, session rotation, abuse detection | expired/revoked sessions purged 7 days after expiry (`purge_operational_data`, daily); reset tokens likewise | nobody reads them in plaintext (tokens are stored only as SHA-256 hashes); DB administrators can see hashes and IPs | **yes** — all sessions and reset tokens deleted |
| **Favourites**: teams, competitions, matches | `favourite_*` | personalisation, notifications | until erasure/unfollow | the user | yes |
| **Devices / push endpoints**: Expo token or web-push endpoint + keys | `devices` | deliver notifications | until the user removes it, or the provider reports it gone | the worker (to send); not exposed by any API | yes |
| **Notification settings and history**: preferences, delivery ledger, content-notification caps | `notification_preferences`, `notification_log`, `content_notification_*`, `social_notification_log` | preferences; de-duplication (never notify twice) | until erasure | the user (settings); the worker (ledger) | yes |
| **Search history**: recent queries per user | `recent_searches` | convenience | until the user clears it or erasure; a query is only ever shown publicly as "popular" after ≥ 3 different viewers selected a result | the user | yes |
| **Community**: comments, likes, reactions, poll votes, reports filed | `comments`, `comment_likes`, `reactions`, `poll_votes`, `comment_reports`, `profile_reports` | the community features | until erasure | everyone sees visible comments (name + text); reactions/votes are shown as counts only | comments **anonymised** (`[deleted]`, structure kept so replies stay readable); likes, reactions, votes, reports **deleted** |
| **Editorial**: articles/revisions authored by staff | `articles`, `article_revisions` | publishing | indefinitely (the publication's record) | public when published | staff accounts cannot self-erase (hand-over first); authorship pointer is set NULL if an operator removes the user row |
| **Subscription**: plan, status, period, processor customer/subscription ids | `subscriptions`, `entitlements` | provide Premium; accounting | **retained** after erasure (accounting/tax/chargeback); entitlements granted by an operator are deleted | the user (own status); admins (`/admin/users/{id}`) | subscription rows kept (user reference points at the tombstone); the subscription is cancelled with the processor first |
| **Payment events**: processor event ids, types, sanitised bodies (ids and amounts — **no card data, ever**) | `payment_events` | idempotent webhook processing; audit | retained with the subscription records (legal) | admins/DB only | kept |
| **Audit log**: who did what administrative action to what, when, why | `audit_log` | accountability, incident response | **12 months minimum**, never auto-purged (policy decision); actor id becomes NULL if the actor's row is removed but the label (`user:12 (admin)`) stays | admins (`/admin/audit-log`) | kept; contains no email addresses or secrets |
| **Operational**: failed background jobs (task, error text with credentials scrubbed, entity id), request ids | `failed_jobs`, logs | operations | resolved 30 days, unresolved 90 days; application logs per your log platform (recommend 30 days, JSON, no PII fields) | admins | n/a (no personal data by design) |
| **Engagement counters**: anonymous view/search counts per article/team/player | `engagement_buckets`, Redis | trending, popularity | 30 days of hourly buckets | internal | n/a (not linked to a user) |
| **Football data**: competitions, teams, players, matches, events, statistics | many tables | the product | indefinitely | public | n/a |
| **Media**: images uploaded by staff (re-encoded, metadata stripped) | S3 bucket + `media*` | articles | until deleted by staff | public by URL when published | n/a |
| **Backups** | encrypted dumps | disaster recovery | 7 daily / 4 weekly / 6 monthly | operators with the backup passphrase | **erased users reappear if a backup is restored** — see below |

## Erasure (`DELETE /api/v1/users/me`) in detail

Requires the current password (so a hijacked session cannot destroy an account), is rate-limited (5/hour), refuses staff
roles, and **cancels any subscription at the processor first** — if the processor cannot be reached the request fails with
502 and nothing is erased, so the person is never left paying for an account they cannot reach. It then deletes or
anonymises as in the table, records an `account.delete` audit entry, revokes every session, and clears the browser cookies.
Covered by `apps/api/tests/test_account_lifecycle.py` (15 tests).

**Backups and erasure.** Erasure is applied to the live database only. Backups are immutable and expire on the schedule
above (6 months for the oldest monthly). If a backup is restored, re-run the erasures requested since it was taken: keep
the list of `account.delete` audit entries (they survive in the audit log, which is part of the backup — replay the
list from the live database's audit log *before* restoring over it, or from the most recent log export). This is a
documented limitation, listed in the launch checklist.

## Export (`GET /api/v1/users/me/export`)

JSON with the account, favourites, notification settings, devices (platform and dates only — never push tokens), search
history, the user's comments, reactions, poll votes, subscription status (plan, period — no processor ids) and
entitlements. It never includes password hashes, tokens, IP addresses, audit entries, other people's data, or payment
credentials. Rate-limited to 5/hour. Web and mobile both offer it under *Profile → Your data*.

## Third parties that receive data

| Party | What they receive | Why |
|---|---|---|
| Football data provider (API-Football) | league/team/player/match queries; **no user data** | live data |
| Payment processor (Stripe) | email, plan, user id (as metadata) | billing |
| Expo push service / browser push services | push tokens and notification text | notifications |
| SMTP relay | recipient email + reset link | password reset |
| Object storage / CDN | uploaded editorial images | media |
| Error/log platform (yours) | structured logs: user ids, request ids, no emails/tokens/passwords | operations |
