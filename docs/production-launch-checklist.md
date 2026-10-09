# Production launch checklist

Each box says who/what has to make it true. **[done]** = verified in the repository or on the Phase 7 test stack (evidence in brackets). **[you]** = needs your
infrastructure, accounts or a decision — Claude could not do it. Nothing here is ticked on faith: an unticked box is a gap.

## Infrastructure

- [ ] **[you]** Production environment provisioned (Docker host(s), `docker compose` ≥ 2.24) — `docs/deployment/production.md`
- [ ] **[you]** **HTTPS enabled** (load balancer / Caddy / Cloudflare in front of nginx) and `PUBLIC_ORIGIN`, `PUBLIC_WS_ORIGIN` are `https://` / `wss://`
- [ ] **[you]** **DNS configured** for the site; `ALLOWED_HOSTS` set to it
- [ ] **[you]** Real object storage (S3/R2) bucket with versioning; `S3_*` set; `MEDIA_PUBLIC_BASE_URL` pointing at a CDN if used
- [ ] **[you]** SMTP relay configured (`SMTP_*`) — **without it nobody can reset a password**; send a test reset to a real mailbox
- [ ] **[you]** Football provider plan sized for the poll cadence (`LIVE_POLL_INTERVAL_SECONDS`) and `FOOTBALL_API_KEY` set
- [ ] **[you]** Stripe live keys + webhook endpoint registered at `https://<site>/api/v1/billing/webhook`; `BILLING_PROVIDER=stripe`
- [ ] **backups enabled** — cron for `deploy/backup/backup.sh` + `restore_verify.sh` **[you]**, scripts and procedure **[done]** (`docs/disaster-recovery/backup-restore.md`)
- [ ] **monitoring enabled** — Prometheus + Grafana in the compose files **[done]**; Alertmanager/pager wired to `monitoring/prometheus/alerts.yml` **[you]**; node-exporter textfile collector or heartbeat URL for backups **[you]**
- [ ] **[you]** Postgres sized: `max_connections` ≥ `(DB_POOL_SIZE + DB_MAX_OVERFLOW) × (uvicorn workers + celery processes)` (+ headroom); `shared_preload_libraries=pg_stat_statements`

## Security

- [ ] **[you] ROTATE THE FOOTBALL PROVIDER API KEY — it is in git history (`API-key.txt`, commit `07febe5`).** Decide whether to rewrite history. (`findings.md` S-1)
- [x] production configuration validation: the API refuses to boot with weak secrets, wildcard/local CORS, `ALLOWED_HOSTS=*`, the test billing provider, default passwords (`production_checks.py`, 28 tests) **[done]**
- [ ] **[you]** secrets generated and stored in a secret manager (`.env.production` never in git; `.env.production.example` has the list) — compose refuses to start without them **[done]**
- [x] security scans passing — Bandit 0 medium/high, pip-audit 0, web production npm audit 0, Semgrep 0 errors, Gitleaks clean history scan, Trivy web 0 / API 0 critical (`docs/security/scanning.md`) **[done]**; CI enforces them **[done, not yet run on GitHub]**
- [x] security headers configured — web CSP (nonce) + HSTS + nosniff + frame/referrer/permissions; API strict headers **[done]**; **[you]** open the staging site with devtools and confirm no CSP violations in the console (no browser was available to verify)
- [x] authentication reviewed (`docs/security/threat-review.md` §1, `test_auth_hardening.py`) **[done]**
- [x] authorization reviewed — endpoint-by-endpoint matrix of 152 operations, IDOR tests (`test_authorization_matrix.py`) **[done]**
- [x] payment security reviewed — signature, replay, idempotency, ordering, premium cannot be forged (`test_billing_consistency.py`) **[done]**
- [x] uploads reviewed (format whitelist, re-encode, limits, traversal) **[done]**
- [ ] **[you]** `/.well-known/security.txt` or a security contact published; decide the vulnerability-reporting process
- [ ] **[you]** Review `docs/security/accepted-risks.md` and sign off on each item

## Database

- [x] migrations verified — fresh DB, upgrade from previous revision with data, downgrade/upgrade, no drift from the models (`test_migrations.py`, 7 tests) **[done]**
- [x] backups tested, **restore tested** — 304 MB database restored and served by the API in 134 s (`docs/disaster-recovery/backup-restore.md`) **[done]**; **[you]** repeat on staging with production-sized data and record the real RTO
- [x] indexes reviewed from measured queries; 4 added, FK audit done (`docs/operations/database.md`) **[done]**
- [ ] **[you]** decide `notification_log` retention (grows without bound) and the audit-log retention (12 months minimum recommended)
- [ ] **[you]** WAL archiving / PITR (or a managed Postgres) if an RPO below the backup interval is required

## Performance

- [x] load tests completed — 7 scenarios, 1 vs 3 workers (`docs/operations/load-testing.md`) **[done, on development hardware]**
- [x] p95 measured per scenario **[done]**
- [x] database performance measured (`pg_stat_statements`, query budgets) **[done]**
- [x] Redis performance measured (memory, clients, ops) **[done]**
- [x] web performance measured and improved (Lighthouse before/after, `docs/operations/performance.md`) **[done]**
- [ ] **[you]** repeat the k6 suite against staging on production-class hardware; set `WEB_CONCURRENCY` from the result (`docs/operations/capacity.md`)

## Application

- [x] web build passes (type errors now fail the build) **[done]**
- [x] mobile type-check, lint, tests pass **[done]**; **[you]** produce store builds (EAS) and test on real devices — offline banner, account deletion, push registration
- [x] backend tests pass **[done]** (`Phase 7 report` has the exact count)
- [x] end-to-end journeys covered at the API level (`test_phase6b_e2e.py`, `test_discovery_e2e.py`, `test_e2e_match_centre.py`, billing consistency, account lifecycle) **[done]**; **[you]** run one manual pass of each journey in a browser on staging (there is no browser E2E harness in the repository)
- [x] production overlay boots, passes startup validation and the smoke test **[done locally]**

## Operations

- [x] health checks work — `/health/live`, `/health/ready`, `/version`; container healthchecks **[done]**
- [x] alerts defined (24 rules, `promtool`-validated) **[done]**; **[you]** deliver them somewhere a human sees
- [x] logs available — structured JSON, request ids across proxy → API → worker **[done]**; **[you]** ship stdout to your log platform (30-day retention suggested)
- [x] runbooks available (`docs/runbooks/`, 10) **[done]**; **[you]** do one game-day: stop Redis, stop Postgres, kill the worker on staging, follow the runbooks
- [ ] **[you]** on-call rota and an escalation path
- [ ] **[you]** at least one administrator created: `python -m app.cli set-role you@example.com admin`

## Privacy and legal (engineering side done; the decisions are yours)

- [x] data inventory with purpose / retention / access / deletion (`docs/security/data-inventory.md`) **[done]**
- [x] account deletion and data export, web + mobile, server-enforced (`test_account_lifecycle.py`) **[done]**
- [ ] **[you]** privacy policy and terms published; legal review of retention (payments, audit log, backups)
- [ ] **[you]** cookie/consent position confirmed (the app sets only essential auth cookies; Vercel Analytics is enabled in production builds — decide whether it needs consent where you operate)
- [ ] **[you]** a process for replaying account erasures after a backup restore

## Go / no-go

Launch when every **[you]** box in *Infrastructure*, *Security* and *Database* is ticked. The rest can follow in the first weeks, in the order listed.
