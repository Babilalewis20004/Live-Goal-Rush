# Accepted risks

Risks that were assessed, are not fixed in Phase 7, and why that is acceptable *for now*. Each has an owner-review trigger:
revisit when the trigger happens or by the date, whichever comes first. Anything not on this list and not fixed is an open
finding in `findings.md`.

| ID | Risk | Why it is acceptable | Compensating control | Revisit |
|---|---|---|---|---|
| S-20 | Access tokens (JWT, 15 min) cannot be revoked individually; a stolen one works until it expires | Every authenticated request re-reads the user from Postgres, so **suspension, deactivation, erasure and role changes take effect immediately**; password change and reset revoke every refresh token; lifetime is short | refresh-token rotation with reuse detection; `ACCESS_TOKEN_EXPIRE_MINUTES` ≤ 60 is warned about at startup | if sessions ever carry sensitive actions beyond today's (e.g. payouts) |
| S-21 | Bandit LOW: 13 × `try/except/pass`, 2 × `random` (retry jitter), 4 × "hardcoded password" (string constants naming the known-bad defaults the validator rejects). Semgrep: 3 × "logger credential disclosure" (log *messages* that contain the word "token"/"reset", with no secret in the arguments), 2 × SHA-1 (content fingerprints, `usedforsecurity=False`) | all reviewed individually; none handles a secret or an authorisation decision | CI fails on Bandit medium+ and Semgrep ERROR | each release |
| S-22 | `npm audit` on `apps/mobile`: 49 high + 16 moderate in the Expo CLI / Metro / Jest / React Native tooling chain (critical `shell-quote` was fixed non-breakingly) | build- and test-time tools; **none is bundled into the shipped app or runs in production**; the fixes require major upgrades (Expo SDK, Jest) that need device testing | CI blocks new *critical* advisories; run builds only from trusted checkouts and CI | the next Expo SDK upgrade (planned for Phase 8) |
| S-23 | Trivy: 44 HIGH in the API image, all Debian 13 base packages (`util-linux`, `ncurses`, `systemd` libs, `perl-base`, `libacl`, …) with **no fix released upstream** | the API container runs one unprivileged Python process, with no shell login, no exposed services but 8000, a read-mostly filesystem; these libraries are not reachable by request data; OS patches already applied at build | `apt-get upgrade` on every build; CI uses `--ignore-unfixed` so a *fixable* HIGH fails the build | monthly image rebuild; consider a distroless/Chainguard Python base |
| S-24 | While Redis is down, rate limits fail **open** (login, search, comments, …) | the alternative (fail closed) turns a Redis outage into a total sign-in outage. Brute force against bcrypt-hashed passwords is slow, and per-account limits resume the moment Redis returns | nginx `limit_req` (30/min on `/auth`, 600/min on `/api`) is independent of Redis; the outage is alerted within a minute | if credential-stuffing is observed (`LoginFailureSpike`) |
| S-25 | `POST /auth/register` returns 409 for an address that already has an account | needed for a usable sign-up form; the only way to avoid it is email-verification-first sign-up, a product decision | 5 registrations/hour/address; password-reset and login do **not** reveal existence (tested) | if email verification is added |
| S-26 | `/health/live`, `/health/ready`, `/health` and `/version` are public | they reveal only "ok/unavailable" per dependency and the release number — useful to attackers only marginally, essential to load balancers | `/metrics` and the API schema are not routed by nginx and are off in production | — |
| S-27 | SHA-1 is used to fingerprint event/lineup payloads | not a security use: it detects "did this content change", an attacker gains nothing from collisions | marked `usedforsecurity=False` | — |

## Known limitations that are *not* risks but readers should know

* **Erased users and backups.** Account erasure is applied to the live database. A restored backup contains users erased since it was
  taken; the erasure list must be replayed after a restore (`docs/security/data-inventory.md`).
* **Notifications are at-most-once per event.** The dedup ledger is claimed *before* sending, so a worker killed between claiming and
  sending loses that notification rather than risking a duplicate. Chosen deliberately: a duplicated goal alert is worse than a missed one.
* **CSRF.** Cookie-authenticated requests are protected by `SameSite=Lax` cookies, JSON-only mutating endpoints, and CORS that allows
  only the configured origins; mobile uses bearer tokens (no ambient credentials). There is no CSRF token. If a subdomain you do not control
  ever shares the cookie domain, add one (`docs/security/threat-review.md`).
