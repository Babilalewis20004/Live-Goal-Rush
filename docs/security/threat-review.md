# Security review — how each area works, what was checked, what was found

Companion to `findings.md` (the list of problems) — this page records *how the system defends itself* and the evidence.
"Tests" are in `apps/api/tests/`; counts are from the Phase 7 final run.

## 1. Authentication

| Property | Implementation | Evidence |
|---|---|---|
| Password storage | bcrypt via passlib, deprecated schemes auto-upgrade; 8–128 chars | `core/security.py` |
| Access token | HS256 JWT, 15 min, `type=access`; `alg=none`, wrong key and refresh-typed tokens rejected; **no role/entitlement/premium claim is trusted** — the user row is re-read per request | `test_auth_hardening.py` |
| Refresh token | 32 random bytes, only the SHA-256 stored, rotated on every use, **reuse of a rotated token revokes the whole family**, 30-day expiry | `test_auth.py`, `test_auth_hardening.py` |
| Sessions | web: `httpOnly`, `SameSite=Lax`, `Secure` in staging/production cookies; mobile: bearer tokens in secure storage | cookie test per environment |
| Brute force | per-IP (10/min) **and** per-account (5/min, case-insensitive) login limits in Redis; nginx `limit_req` independent of Redis; bcrypt cost | `test_auth_hardening.py` |
| Enumeration | login: same body and a decoy bcrypt for unknown emails; reset: identical response and the email is sent off the request path; registration: 409 (accepted, S-25) | tests |
| Password reset | single-use, 30 min, hashed at rest; revokes all sessions on use; **emailed, never returned or logged outside development** | `test_password_reset_email.py` |
| Logout / change password | revokes the refresh token / all sessions | `test_auth.py` |
| Account deletion | password required, subscription cancelled first, personal data erased (`data-inventory.md`) | `test_account_lifecycle.py` |
| Suspension | enforced on every request, sign-in and refresh | `test_auth_hardening.py` |

## 2. Authorization

* **Roles** (`user`, `author`, `editor`, `admin`) live in the database and are checked by dependencies that run *before* body validation
  (`EditorDep`, `ReviewerDep`, `AdminDep`). The per-article rules (an author edits only their own drafts) live in `ArticleService`.
* **The matrix test** (`test_authorization_matrix.py`) enumerates every operation from the OpenAPI schema and requires it to be on the
  explicit public allow-list or to refuse an anonymous caller (adding a public endpoint without updating the list fails CI). Staff-only
  and admin-only routes are probed as every lower role.
* **IDOR.** Every user-owned resource query filters on the caller's id in SQL (devices, favourites, preferences, subscription, export,
  deletion); tests act as two users and assert that A cannot see or alter B's data. Findings: none beyond S-15 (an ordering issue).
* **Profiles** are invisible (404) until their owner publishes them, and a private profile cannot even be probed via the report endpoint.
* **Admin API** (`/api/v1/admin/*`) is ADMIN-only on the server; editors cannot reach it.

## 3. Premium and payments

* Entitlements are computed from the database (`entitlements_for`) on **every** request — not cached, not read from the token, cookies,
  headers or query string. Tests try each of those channels plus a forged JWT carrying `premium`, `entitlements` and `role=admin`.
* Checkout returns a URL and **grants nothing**; the only path to Premium is a verified webhook. There is no client-callable "payment succeeded" endpoint (tested).
* Webhooks: HMAC-SHA256 over `timestamp.body`, constant-time compare, 5-minute replay window, 256 KB cap, idempotent on the processor's event id
  (unique row claimed first, so 8 simultaneous deliveries apply once), failures stored and retried on redelivery, **events ordered by the processor's timestamp** (S-8),
  the `test` provider refused in production (also enforced at startup).
* Consistency matrix tested: payment succeeds / fails (grace then access ends) / subscription expires / renews / cancelled (access to period end) / webhook duplicated /
  delayed / out of order / user on another device (identical entitlements).
* Stored payment data: ids and amounts only. No card data reaches or is stored by this system.

## 4. User-generated content

| Input | Treatment |
|---|---|
| Comments, polls, profile fields | stored and returned as **plain text**; web renders through React (escaped), mobile through `<Text>`; length, link-count, duplicate and rate limits; reports auto-hide at 3 |
| Article body (HTML) | server-side allow-list sanitiser (tags, attributes, URL schemes, image hosts), covered by 30 tests; stored sanitised |
| Search / `q` parameters | parameterised SQL only; `LIKE` wildcards escaped; length-bounded |
| Uploads | bytes judged by Pillow, format whitelist (JPEG/PNG/WebP/GIF — SVG, PSD, PDF rejected), pixel/dimension/size limits, re-encoded to WebP with all metadata and appended data dropped, storage keys generated server-side and validated (no path traversal), served `immutable` with `nosniff`, kept in object storage / `media-data` outside the code tree, size capped again by the request-size middleware; Pillow upgraded (S-2) |
| JSON bodies | pydantic validation; 1 MB cap |

## 5. Transport, headers, CORS

* Web: nonce-based CSP (`script-src 'self' 'nonce-…' 'strict-dynamic'`, no `unsafe-inline`/`unsafe-eval` in production, `object-src 'none'`,
  `frame-ancestors 'none'`, `connect-src` limited to the API and its WebSocket), HSTS, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, COOP.
  `style-src-attr 'unsafe-inline'` is allowed because component libraries set `style=""` attributes; attributes cannot run script.
  The payment provider needs no CSP allowance: checkout is a top-level redirect. Images are allowed from any https host because article images may come from anywhere (`ARTICLE_IMAGE_ALLOWED_HOSTS` restricts which URLs editors may save).
* API: `nosniff`, `X-Frame-Options`, `Referrer-Policy: no-referrer`, a deny-all CSP (it serves JSON/images, never pages), HSTS when deployed, `no-store` on credentialed paths.
* CORS: exact origins from `CORS_ORIGINS` (no `*`; the validator refuses it in deployed environments); credentials allowed only for those.
* WebSocket: `Origin` must be in `CORS_ORIGINS`; capacity and per-address caps; messages ≤ 2 KB and JSON-validated; optional token.
* **CSRF.** Browser requests that change state are JSON `POST/PUT/PATCH/DELETE` with `SameSite=Lax` cookies. A cross-site page can neither send those cookies on
  such requests nor read responses (CORS), and cannot send `application/json` cross-origin without a preflight that fails. No anti-CSRF token is needed while the
  web app and API share a registrable domain and no untrusted sibling subdomain exists. Mobile uses bearer headers, so it has no ambient credentials to abuse.

## 6. Rate limiting and proxy trust

Redis fixed windows (atomic) per IP and per user: register 5/h, login 10/min + 5/min/account, reset 5/h, search 60/min, comments 5/min and 40/h, reactions 30/min, votes 20/min,
uploads 20/min and 200/day, checkout 10/h, data export 5/h, account deletion 5/h, analytics 240/min, webhook 120/min. The client address is the TCP peer unless the peer is in
`TRUSTED_PROXY_CIDRS`, in which case the first valid `X-Forwarded-For` entry is used; nginx *overwrites* that header with the address it saw, so a client-supplied value never survives.
uvicorn's own proxy-header rewriting is disabled so a direct client cannot forge its address. Tests: `test_client_ip.py`, WebSocket per-address cap test.

## 7. Operational security

* Secrets: none in images or the repository (Trivy secret scan, Gitleaks) except S-1 in *history*; production compose requires every secret; startup refuses weak ones.
* Least privilege: all containers run as non-root; nginx has `cap_drop: ALL`, `no-new-privileges`, read-only root; only nginx publishes a port.
* Audit trail: role changes, entitlement grants/revocations, suspensions, comment/profile moderation, article deletion, failed-job resolution and account erasure are recorded atomically with the action, append-only, with actor, target, time and reason (`GET /api/v1/admin/audit-log`).
* Logs: structured JSON; passwords, tokens, secrets, cookies, authorisation headers and e-mail addresses are redacted by key and never logged by value; request ids correlate proxy → API → worker.
