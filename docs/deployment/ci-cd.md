# CI/CD

Two GitHub Actions workflows (`.github/workflows/`). **They have not been executed in this repository's GitHub** —
the repository had no CI before Phase 7 and these were written and validated locally (every command in them was run
by hand against the real stack; see the Phase 7 report). Expect to fix small environment details on the first run.

## `ci.yml` — every pull request and push to `main`

| Job | Runs | Fails the build when |
|---|---|---|
| `backend` | Postgres + Redis services, `alembic upgrade head`, `pytest --cov=app` | any test fails, migrations don't apply or branch, coverage < the floor (80 %) |
| `backend-security` | Bandit `-ll` (medium+), `pip-audit -r constraints.txt` | a medium/high finding, or any known CVE in the exact versions the image installs |
| `web` | `tsc --noEmit`, `eslint`, `vitest`, `next build`, `npm audit --omit=dev --audit-level=high` | type error (the build also stopped ignoring them), lint error, test failure, high/critical production advisory |
| `mobile` | `tsc --noEmit`, `expo lint`, `jest`, `npm audit --audit-level=critical` | same; high advisories in the Expo/Jest toolchain are tracked in `docs/security/accepted-risks.md` |
| `secrets` | Gitleaks over the full history | a secret is found |
| `sast` | Semgrep (`p/python`, `p/typescript`, `p/secrets`), `--severity ERROR` | an ERROR-severity finding |
| `images` | production-overlay `config` check, build api + web, **Trivy** (fixable HIGH/CRITICAL + secrets in layers), start the stack, **smoke test** | the overlay renders without secrets, a fixable vulnerability, or the smoke test fails |
| `gate` | depends on all of the above | any of them did not succeed |

**Branch protection** (Settings → Branches → `main`): require the `CI gate` status check, require review, disallow force
pushes. The gate job exists so a new job can be added without editing branch-protection rules.

## `deploy.yml` — tags `vX.Y.Z`

```
tag vX.Y.Z → verify CI gate was green on that commit → build + push images (ghcr.io, tagged version and sha)
           → staging: migrate, roll, smoke test
           → [production environment: manual approval by required reviewers]
           → production: migrate, roll, smoke test
```

* Production is **never** deployed from a branch push. Configure the `production` environment in GitHub with required
  reviewers; that approval is the safeguard.
* Each deploy (`.github/actions/deploy`) SSHes to the host, pulls the release's images, runs `alembic upgrade head` as a
  one-off container (expand-only migrations, `docs/deployment/migrations.md`), rolls `api worker scheduler web nginx`
  with `--wait` (compose waits for healthchecks), records the release in `.release`, then smoke-tests the **public**
  origin including `--edge` (verifies `/metrics` and the OpenAPI schema are not reachable from outside) and
  `--expect-version`.
* If the smoke test fails the job fails and prints the rollback command: `./deploy/rollback.sh` on the host.

### Configure once

| Where | Name | Value |
|---|---|---|
| Environment `staging` / `production` → variables | `PUBLIC_ORIGIN` | `https://staging.example` / `https://example` |
| Environment secrets | `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` | SSH access for a deploy-only user that can run `docker compose` in `/opt/livepitch` |
| Host, `/opt/livepitch/.env.production` | every variable in `.env.production.example` | **secrets live on the host or in a secret manager, not in GitHub Actions logs** |
| Host, `/opt/livepitch` | the repo checkout (compose files, `deploy/`) | updated by the pipeline or `git pull` |

The version shown by `/version` comes from `APP_VERSION` (set from the tag) and `GIT_SHA`.

## Versioning

Semantic versioning, one version for the whole product (`API`, web and mobile ship together). The API reports it at
`GET /version` and in the OpenAPI document. Bump `app_version` in `apps/api/app/core/config.py` (and the web/mobile
`package.json` `version`) in the release commit; release notes go in `docs/release-notes/vX.Y.Z.md`. The previous
release was implicitly `2.0.0` (the version FastAPI reported before Phase 7); Phase 7 is **2.1.0**.

## Rollback

`docs/runbooks/rollback.md`. Application rollback is one command and does not touch the database.
