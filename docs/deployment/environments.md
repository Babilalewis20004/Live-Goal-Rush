# Environments and configuration

`ENVIRONMENT` selects the behaviour set. Only `staging` and `production` are "deployed": they run the startup
configuration checks (`apps/api/app/core/production_checks.py`) and refuse to boot on an unsafe configuration, set
`Secure` on auth cookies, send HSTS, and switch off `/docs`, `/redoc` and `/openapi.json`.

| | development | test | staging | production |
|---|---|---|---|---|
| Purpose | local work | pytest / CI | pre-production rehearsal | real users |
| Startup validation | none | none | **errors block boot**; https/billing-test issues are warnings | **all errors block boot** |
| Billing provider | `test` (self-signed webhooks) | `test` | `stripe` in test mode (or `test`, warned) | `stripe` only |
| CORS / PUBLIC_API_URL | localhost allowed | localhost | https origins | https origins only, no localhost |
| `ALLOWED_HOSTS` | `*` | `*` | list your hosts (warned if `*`) | **required** |
| Secrets | insecure defaults so it boots | defaults | real | real, in a secret store |
| Redis | open | fakeredis | password | password + `volatile-lru` + AOF |
| API docs | on | on | off | off |
| Log format | text or JSON | — | JSON | JSON |
| Reset-password link | returned in the response (dev convenience) | same | never returned or logged | never returned or logged |

## What the validator enforces (staging + production)

Errors (boot refused): weak/default/short `JWT_SECRET` (< 32 chars or low entropy), non-HMAC `JWT_ALGORITHM`, default or
missing database password, wildcard/empty `CORS_ORIGINS`, missing `FOOTBALL_API_KEY`, `STRIPE_SECRET_KEY` missing,
default or short `BILLING_WEBHOOK_SECRET`, missing/placeholder S3 credentials, unknown billing provider.
**Production-only errors, warnings in staging:** Redis without a password or TLS, `localhost`/non-https CORS origins,
`ALLOWED_HOSTS=*`, non-https `PUBLIC_API_URL`/billing URLs, empty `TRUSTED_PROXY_CIDRS`, `BILLING_PROVIDER=test`.
Warnings (logged): local media backend, access token lifetime > 1 h, VAPID keys missing, non-JSON logs.
Every rule is unit-tested in `apps/api/tests/test_production_checks.py`.

## Variable reference

Authoritative templates: `.env.example` (development) and `.env.production.example` (production). Grouped:

| Group | Variables | Notes |
|---|---|---|
| Identity | `ENVIRONMENT`, `APP_VERSION`, `GIT_SHA`, `SERVICE_NAME` | version/sha are stamped by CI |
| Public address | `PUBLIC_HOST`, `PUBLIC_ORIGIN`, `PUBLIC_WS_ORIGIN`, `PUBLIC_API_URL`, `CORS_ORIGINS`, `ALLOWED_HOSTS`, `TRUSTED_PROXY_CIDRS` | one origin behind nginx |
| PostgreSQL | `DATABASE_URL`, `POSTGRES_*`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, `DB_POOL_RECYCLE_SECONDS`, `DB_STATEMENT_TIMEOUT_MS` | pool sizes are **per process** |
| Redis | `REDIS_URL`, `REDIS_PASSWORD`, `REDIS_MAXMEMORY`, `REDIS_*_TTL_SECONDS` | TTL meanings: `docs/operations/redis.md` |
| Auth | `JWT_SECRET`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `RATE_LIMIT_*` | |
| Football data | `FOOTBALL_DATA_PROVIDER`, `FOOTBALL_API_KEY`, `FOOTBALL_API_BASE_URL`, `FOOTBALL_API_LEAGUE_IDS`, poll intervals | |
| Billing | `BILLING_PROVIDER`, `STRIPE_SECRET_KEY`, `BILLING_WEBHOOK_SECRET`, `BILLING_*_URL`, `BILLING_GRACE_DAYS` | |
| Media | `MEDIA_STORAGE_BACKEND`, `S3_*`, `MEDIA_PUBLIC_BASE_URL`, `MEDIA_MAX_BYTES` | |
| Push | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | optional |
| Limits | `MAX_REQUEST_BODY_BYTES`, `WEBSOCKET_MAX_CONNECTIONS(_PER_IP)`, `WEBSOCKET_SEND_TIMEOUT_SECONDS`, `CELERY_TASK_*_LIMIT_SECONDS` | |
| Web build | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_BROWSER_API_URL`, `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_WS_URL` | `NEXT_PUBLIC_*` are fixed at build time |

## Secrets audit (what was found in Phase 7)

* `.env` files are git-ignored; only `*.example` files are tracked (verified with `git ls-files`).
* **The football provider API key was committed in `API-key.txt` in commit `07febe5` and is still in git history**
  (the file is staged for deletion, which does not remove history). The same key is the one in the developer `.env`.
  **Rotate it with the provider.** Rewriting history is a separate decision for the repository owner. See
  `docs/security/findings.md` (S-1).
* The images contain no secrets (`.dockerignore` excludes `.env*`; Trivy secret scan: 0 findings).
* Production secrets are required by the compose overlay and have no defaults anywhere in the production path.
