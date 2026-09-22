# Authentication Architecture (Phase 3)

## The goal

> Users should be able to create an account, log in securely, and stay
> logged in across sessions on web and mobile, without weakening the
> public, unauthenticated livescore experience Phase 1/2 already shipped.

Phase 1/2 had no user concept at all — every endpoint was public, and the
WebSocket layer's own docstring explicitly called itself
"authentication-ready" but not authenticated (`app/api/v1/websocket.py`).
Phase 3 builds real accounts on top of that, without touching how an
anonymous visitor experiences the app.

## Token strategy

Short-lived JWT access tokens (15 min default) + longer-lived, rotating
refresh tokens (30 days default), issued by `app/services/auth_service.py`
and signed/verified in `app/core/security.py` (PyJWT, HS256).

**Transport differs by client, not by token shape:**

- **Web** — `access_token`/`refresh_token` are set as `HttpOnly`,
  `SameSite=Lax` cookies by every `/auth/register`, `/auth/login`, and
  `/auth/refresh` response. A page's own JavaScript never sees the raw
  token — `apps/web/lib/api.ts` sends `credentials: "include"` and lets
  the browser attach the cookie automatically; Server Components forward
  the incoming request's `Cookie` header by hand
  (`apps/web/lib/server-auth.ts`), since Node's `fetch` has no browser
  cookie jar to do that for you.
- **Mobile** — no cookie jar worth relying on, so a request carrying
  `X-Client: mobile` gets the raw tokens back in the JSON response body
  too (`TokenResponse` in `app/schemas/user.py`). The Expo app
  (`apps/mobile/src/lib/auth-storage.ts`) stores them in
  `expo-secure-store` (Keychain/Keystore-backed, never `AsyncStorage`) and
  sends `Authorization: Bearer <token>` on every request
  (`apps/mobile/src/lib/api.ts`).

`app/api/deps.py::get_current_user` accepts either the `Authorization`
header or the `access_token` cookie — whichever is present — so the same
route works for both clients without branching.

## Refresh rotation + reuse detection

Every `/auth/refresh` call:

1. Looks up the presented refresh token by its SHA-256 hash
   (`RefreshToken.token_hash` — the raw token is never stored).
2. If it's already `revoked_at`-marked, treats this as a stolen/replayed
   token and revokes **every** active refresh token for that user
   (`AuthService._revoke_all_for_user`), forcing re-login everywhere.
3. Otherwise, issues a new access + refresh token pair, marks the
   presented one `revoked_at` + `replaced_by_id` pointing at the new row,
   and returns the pair.

This is the standard defense against a refresh token being copied and
replayed after the legitimate client has already rotated past it — replay
of an old token is detectable specifically because a *newer* one already
exists for that chain.

Changing your password (`POST /users/me/password`) and confirming a
password reset both call `_revoke_all_for_user` too, so a compromised
password can't be used to keep an old session alive after it's changed.

## Password storage

`passlib[bcrypt]` (`app/core/security.py::hash_password`/`verify_password`).
**Pinned dependency note:** `passlib` 1.7.4 (its last release) predates
`bcrypt`'s 4.1 stricter 72-byte validation and breaks at import time
against it — `requirements.txt` pins `bcrypt>=4.0,<4.1` as the documented
workaround.

## Password reset

`POST /auth/password-reset/request` always returns `202` with the same
generic message regardless of whether the email exists — no account
enumeration. No real email-sending infrastructure exists in this repo (by
design — see the mock football provider's own rationale), so "delivery"
is a clearly-labeled dev stub: `AuthService.request_password_reset` always
logs the reset link server-side, and additionally returns it in the
response body under `dev_reset_url` **only** when
`ENVIRONMENT != production`. Reset tokens are single-use
(`PasswordResetToken.used_at`), time-limited
(`PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`), and stored hashed like refresh
tokens.

## Rate limiting

No rate-limit infrastructure existed before Phase 3. `app/core/rate_limit.py`
adds one small primitive — `RedisService.incr(key, ttl_seconds)`, a
fixed-window counter that sets its TTL only on the window's first
increment — rather than a new library. `rate_limiter(bucket, limit,
window_seconds)` returns a FastAPI dependency applied to
`/auth/register`, `/auth/login`, and `/auth/password-reset/request`
(IP-keyed). Login additionally has a tighter, email-keyed limit inside
`AuthService._check_login_rate_limit` (5/minute by default) — this slows
credential stuffing against one specific account even from rotating IPs,
which a purely IP-keyed limit wouldn't catch. Every check **fails open**
on a Redis error, matching `CacheAside`'s existing "don't let infra
trouble break a request" principle.

## WebSocket auth

`app/api/v1/websocket.py` had a documented-but-unimplemented extension
point (`_origin_allowed`, the guard before `manager.connect_general`/
`connect_match`). Phase 3 adds an **optional** `token` query parameter to
both `/ws/matches` and `/ws/matches/{match_id}`: if present, it's decoded
the same way as an HTTP request's bearer token; invalid → the connection
is closed with `WS_1008_POLICY_VIOLATION`, exactly like the existing
origin/capacity checks. If **absent**, behavior is byte-for-byte
unchanged from Phase 2 — anonymous WebSocket connections still work,
preserving the public real-time board exactly. The resolved user id is
kept only for logging; `ConnectionManager`/`PubSubBridge` remain entirely
unaware of users — notification delivery is a fully separate consumer of
the same event stream (see `notifications.md`), never routed through the
WebSocket layer.

## Database

`users`, `refresh_tokens`, `password_reset_tokens` — see
`alembic/versions/b4a59e9fb1c9_phase_3_authentication.py` for the full
schema and constraint rationale.

## Environment variables

See `apps/api/.env.example`: `JWT_SECRET` (**must** be overridden outside
local dev — the checked-in default is intentionally public),
`JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`,
`REFRESH_TOKEN_EXPIRE_DAYS`, `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`,
`RATE_LIMIT_*`.

## Tests

`apps/api/tests/test_auth.py` — registration, login, refresh
rotation/reuse detection, logout, profile/password management, password
reset flow, rate-limit trip. `apps/api/tests/conftest.py`'s
`authenticated_client` fixture (mints a token directly rather than going
through `/auth/login`) is what every later Phase 3 test file builds on.
