# Phase 7 security findings

Every finding from the Phase 7 audit, scanners and targeted testing, including the ones that are **not** fixed.
Severity is the impact if exploited or left alone in production, judged for this application. *Origin* says whether the
problem existed before Phase 7 (**existing**) or came with Phase 7 changes (**introduced** — none survived to the end;
those caught during the work are listed under "introduced and fixed in-phase"). Status: **fixed**, **open** (needs an
action Claude could not take), or **accepted** (with the reasoning in `accepted-risks.md`).

## Summary

| Severity | Existing — fixed | Existing — open | Existing — accepted | Introduced |
|---|---|---|---|---|
| Critical | 1 (S-3) | 0 | 0 | 0 |
| High | 3 (S-2, S-4, S-18) | **1 (S-1)** | 0 | 0 |
| Medium | 9 (S-5 – S-13) | 0 | 3 (S-20, S-22, S-23) | 0 |
| Low | 5 (S-14 – S-17, S-19) | 0 | 3 (S-21, S-24, S-25) | 0 |
| Informational | — | — | 2 (S-26, S-27) | — |

## Open — needs the owner

### S-1 · HIGH · the football provider API key is in git history (existing, **open**)
`API-key.txt` was committed in `07febe5` ("Add Phase 5…") and the file is only *staged for deletion* in the working tree, which
does not remove it from history. The committed value is **identical to the key in the developer `.env`** (compared by hash,
not printed here), i.e. it is a live credential. Gitleaks does not flag it (no recognisable pattern), so no scanner will
ever catch this class of leak.
**Action required:** rotate the key at the provider; then decide whether to rewrite history (`git filter-repo`) — only matters if the
repository has been or will be shared. Claude did not rewrite history or rotate the key (outside what it can do, and destructive).
Prevention added: `.gitignore` covers `.env.*`; CI runs Gitleaks on every PR; `API-key.txt`-style files should go in a secret store.

## Fixed — existing issues

### S-2 · HIGH · Pillow 11.3.0 with 35 known vulnerabilities in the image-upload path
Pillow decodes untrusted images (editor uploads). `pip-audit` reported 35 advisories (out-of-bounds writes in PSD/JPEG2000/TGA
handling, decompression and memory issues) all fixed in 12.3.0; `requirements.txt` capped it at `<12`.
**Fixed:** `Pillow>=12.3,<13`, pinned in `constraints.txt`; the 53 media tests pass on 12.3.0; `pip-audit` now reports none.
Defence in depth that already existed and was re-verified: the format whitelist (SVG/PSD/PDF rejected), pixel and dimension
limits, re-encoding to WebP with metadata stripped, bytes judged rather than filenames or declared types.

### S-3 · CRITICAL · Next.js 16.3.3 advisories (RCE in `next/og` `ImageResponse`, draft-mode cache leak, …) + dev tooling shipped as a production dependency
`npm audit --omit=dev`: 1 critical, 9 high. The app does not use `next/og`, so the RCE was not reachable, but the version was
affected. `shadcn` (a CLI) sat in `dependencies` and dragged in `@modelcontextprotocol/sdk`, `ts-morph`, `fast-glob`, `braces`, `micromatch`.
**Fixed:** `next@16.4.0` (build, 156 tests, type-check and lint all pass), `shadcn` moved to `devDependencies`, `sharp` and
`source-map-js` updated. Production dependency audit: **0 vulnerabilities**. CI now fails on any high/critical production advisory.

### S-4 · HIGH (availability) · goal notifications failed for any team with more than ~8,000 followers
`resolve_targets` inserted every recipient's dedup row in one statement with 4 bind parameters each; the driver allows 32,767,
so the insert raised and **nobody was notified** — precisely for the most-followed teams. Found by the notification load
scenario (8,538 followers). **Fixed:** chunked claims (2,000 per statement; retry-safe because claims are `ON CONFLICT DO NOTHING`);
regression test with 8,300 followers.

### S-18 · HIGH (availability) · missing index on a self-referencing foreign key
`refresh_tokens.replaced_by_id … ON DELETE SET NULL` had no index, so deleting a token scanned the whole table: purging 18,675 of
80,000 expired tokens took **186 s** (1.2 s with the index). It also slowed logout-everywhere, password reset and account
erasure. **Fixed:** `ix_refresh_tokens_replaced_by`; purge now runs in 5,000-row batches.

### S-5 · MEDIUM · the password-reset token was written to the log in every environment
`logger.info("Password reset link …: %s", reset_url)` logged the live token, including in production. Anyone with log access could
take over an account. **Fixed:** the link is emailed (new SMTP sender, sent off the request path) and never returned or logged outside development.

### S-6 · MEDIUM · login timing revealed which emails are registered
An unknown email skipped the bcrypt check, so it returned measurably faster. **Fixed:** a decoy hash is verified, so both paths cost one bcrypt.

### S-7 · MEDIUM · email addresses were case-sensitive
`Bob@x.com` and `bob@x.com` could register as two accounts; the per-account login limit used the raw string (a differently-cased
spelling had a fresh bucket); the operator CLI lowercased and so could not find mixed-case users. **Fixed:** normalised at the schema,
case-insensitive lookup (so accounts created before the fix still sign in), `lower(email)` index.

### S-8 · MEDIUM · payment webhook events could be applied out of order
Deliveries are unordered. A late "cancelled" after a renewal switched off auto-renew; an old `period_end` could shorten a paid period;
a late "payment failed" for an old invoice downgraded an active subscription. **Fixed:** events carry the processor's timestamp and
older-than-applied events are ignored (recorded as `ignored: stale event`); a paid period only ever grows. 16 new consistency tests
(concurrent duplicates, replays, out-of-order, forged claims).

### S-9 · MEDIUM · a rate-limit counter could lose its expiry
`INCR` then `EXPIRE` were two commands; a crash between them left a counter with no TTL — a permanent lock-out for that client. **Fixed:**
one `MULTI/EXEC` with `EXPIRE … NX`, which also self-heals existing TTL-less counters.

### S-10 · MEDIUM · nothing stopped an insecure configuration from running in production
Every setting had a local-development default (`JWT_SECRET=dev-insecure…`, open CORS, test billing provider, default DB password).
**Fixed:** startup validation for `staging`/`production` (`production_checks.py`, 28 tests) refuses to boot and lists every problem; the production
compose overlay has no defaults for secrets.

### S-11 · MEDIUM · no browser-side hardening
No CSP, HSTS, `nosniff`, framing protection, referrer or permissions policy on the web app; `typescript.ignoreBuildErrors: true` hid type errors from builds;
the API sent no security headers. **Fixed:** nonce-based CSP per request (all 27 script tags carry the nonce — verified against the running container),
the other headers via `next.config.mjs`, strict headers + `no-store` for credentialed paths on the API, type errors now fail the build. *Not verified in a real
browser* (no browser available in this environment): confirm there are no CSP console violations on staging (checklist item).

### S-12 · MEDIUM · container hardening
The web image ran as root, shipped dev dependencies and npm (whose bundled `tar`/`glob`/`cross-spawn` carried 1 critical + 9 high advisories) and was 2.0 GB; the API image
contained pytest/fakeredis and the test suite. **Fixed:** multi-stage web image (843 MB), non-root, no package manager, OS patches applied; API image: runtime dependencies only,
non-root with no login shell, no tests, health check, pinned versions. Trivy: web 0 high/critical; API: 0 critical, 44 high all in the Debian base with **no upstream fix**
(accepted, S-23).

### S-13 · MEDIUM · no request-size limit in the application
A client could stream an arbitrarily large body. **Fixed:** 1 MB for JSON (uploads: image limit + 1 MB), enforced on declared length and while streaming; nginx enforces the same first.

### S-14 · LOW · one slow WebSocket client delayed everyone; no per-address connection cap
Broadcast awaited each send in turn with no deadline. **Fixed:** concurrent sends with a 5 s deadline, eviction of clients that stop reading, 25 sockets per address.

### S-15 · LOW · `POST /editor/articles/categories` checked the admin role after validating the body
A non-admin got 422 instead of 403 (and the check lived in the handler). **Fixed:** an `AdminDep` dependency runs before parsing. The authorization matrix test would have caught it.

### S-16 · LOW · interactive API docs and the OpenAPI schema were public in production
**Fixed:** disabled when `ENVIRONMENT` is `staging`/`production`.

### S-17 · LOW (availability/cost) · reads depended on the football provider
`GET /competitions` called the provider on every cache miss (a Redis outage = a provider call per request; a provider outage = HTTP 500), search called it for unknown queries, and every
API start ran a full sync (a crash loop burns the provider quota). **Fixed:** reads serve stored data, search degrades to empty with a per-minute budget, start-up skips the sync when data is < 12 h old.

### S-19 · LOW · the `Cache-Control` of credentialed responses was unspecified
**Fixed:** `no-store` for `/auth`, `/users/me`, `/me`, `/subscription`, `/admin`, `/profiles/me`.

## Accepted (details and review dates in `accepted-risks.md`)
S-20 access tokens are not individually revocable · S-21 Bandit/Semgrep LOW findings · S-22 Expo/Jest/Metro toolchain advisories (49 high, build-time only) ·
S-23 Debian base-image CVEs without fixes · S-24 rate limiting fails open when Redis is down · S-25 registration reveals whether an email is taken ·
S-26 `/health` and `/version` are public · S-27 SHA-1 used as a content fingerprint (not security).

## Introduced and fixed in-phase (never reached a commit)
* The first chunked-body test returned 400, not 413: FastAPI converts exceptions raised while reading a body into its own 400. The limit middleware now overrides that response (test added).
* A `--forwarded-allow-ips='*'` uvicorn flag in the first Dockerfile draft would have let any direct client forge its address and bypass per-IP limits; removed in favour of the application's `TRUSTED_PROXY_CIDRS` logic (uvicorn's own proxy-header handling is off).
* The health endpoints initially probed the database through the global engine, which made readiness untestable and tied to the wrong event loop; they now use the request's injected session.

## Targeted security testing performed (all automated, all passing)

| Area | Tests | What they prove |
|---|---|---|
| Authorization matrix | 201 (`test_authorization_matrix.py`) | every one of the 152 operations (70 public, 82 not) is either on an explicit public allow-list or refuses anonymous callers; 36 staff-only routes refuse plain users; the admin routes refuse every other role; IDOR checks on devices, favourites, preferences, comments, profiles, drafts, subscriptions |
| Premium | 5 of the 27 in `test_billing_consistency.py` | entitlement is server-side only: query params, headers, cookies, forged JWT claims (`premium`, `role`, `entitlements`) grant nothing; there is no "I paid" endpoint |
| Webhooks | 16 + existing 22 | signature, replay window, duplicate (8 concurrent), delayed/out-of-order, forged, oversized |
| Authentication | 21 (`test_auth_hardening.py`) | enumeration, timing decoy, case, rotation + reuse detection, `alg=none`, wrong-type tokens, cookie flags per environment, token hashing |
| Injection / XSS / uploads | existing 53 media, 30 sanitiser, community "inert text" tests | SQL via parameters only; comments stored as text; article HTML sanitised; uploads re-encoded from bytes |
| Request limits | 8 (`test_http_hardening.py`) | 413 on declared and streamed oversize, upload allowance, hostile `X-Request-ID` replaced, Host-header check |
| Rate-limit bypass | existing + atomicity | forged `X-Forwarded-For` ignored from untrusted peers; counters always carry a TTL |
| CSRF | by design, see `threat-review.md` | cookies are `SameSite=Lax`, state changes are non-GET JSON requests that require a CORS-permitted origin or bearer token |
