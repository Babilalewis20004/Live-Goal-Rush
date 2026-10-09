# Database migrations

Alembic, `apps/api/alembic/versions/`. One linear history (a test fails if two migrations share a parent).

## Procedure (every release)

1. **Back up first** — `deploy/backup/backup.sh` (a deploy is the most likely moment to need yesterday's data).
2. **Run migrations once, before the new code serves traffic**, as a one-off container, not from every replica:

   ```bash
   docker compose … run --rm -e RUN_MIGRATIONS=1 --no-deps api alembic upgrade head
   ```
   Application containers start with `RUN_MIGRATIONS=0`. (The image still defaults to `1` so a single-container
   development setup keeps migrating on start.) The CD pipeline does exactly this (`.github/actions/deploy`).
3. **Roll the application** (`up -d --wait`). The previous version keeps serving during step 2 because migrations are
   expand-only (below).
4. **Smoke test** (`apps/api/scripts/smoke.py`) and watch the dashboards for ten minutes.

## Safety rules

Every migration must be safe to run **while the previous application version is still running**, and must leave the
database usable by that previous version if the release is rolled back. That means *expand, then contract*:

| Phase | Allowed in the same release as the code that needs it | Notes |
|---|---|---|
| **Expand** | new tables; new **nullable** columns (or with a server default); new indexes; new enum values stored as strings | deploy the migration, then the code |
| **Migrate data** | backfills in batches from a task, never one giant `UPDATE` in a migration | idempotent and resumable |
| **Contract** | dropping a column/table, adding `NOT NULL` without a default, renaming | only in a **later** release, after no running code reads the old shape |

Practical consequences:

* Never rename a column in one step. Add the new column, write both, backfill, switch reads, then drop the old one two releases later.
* Create large indexes with `CREATE INDEX CONCURRENTLY` (needs `op.get_context().autocommit_block()`); the Phase 7
  indexes are on small-to-medium tables and are created in the normal transactional way.
* Keep each migration small and reversible. The newest one (`c7e0a3f19d42`) has a tested `downgrade()`.

## What is tested

`apps/api/tests/test_migrations.py` runs in CI and locally:

* a single head; every migration has a `downgrade`;
* an empty database upgrades to `head`, and the result **matches the models** (no table or column that one has and the other lacks);
* a database at the previous revision with data in it upgrades without losing the data;
* the newest migration downgrades and upgrades again; running `upgrade head` twice is a no-op.

## Rollback

* **Application only** (the normal case): `./deploy/rollback.sh` — the previous images run against the newer schema.
* **Schema** (only for a bad migration, and only if no data was written that the downgrade would lose):
  `alembic downgrade -1`, then roll the application back. Test the downgrade on a restored copy first.
* **Data loss or a contract migration that went wrong:** restore from backup — `docs/runbooks/backup-restoration.md`
  (measured: a 304 MB database restores in about 80 s; see `docs/disaster-recovery/backup-restore.md`).

## Phase 7 migration (`c7e0a3f19d42`)

Expand-only. Adds `failed_jobs`, `audit_log`, `users.deleted_at`, `subscriptions.last_event_at`, and four indexes chosen
from measured queries (`docs/operations/database.md`): `ix_articles_excerpt_trgm`, `ix_favourite_teams_created`,
`ix_refresh_tokens_replaced_by`, `ix_users_email_lower`.
