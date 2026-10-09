# Rolling back a release

Application rollback is one command and **does not touch the database**, because every migration is expand-only
(`docs/deployment/migrations.md`): the previous version runs fine against the newer schema.

## The normal case: the new version is bad

```bash
cd /opt/livepitch
IMAGE_PREFIX=ghcr.io/<org>/<repo> ./deploy/rollback.sh          # to the release in .release.previous
# or a specific one
IMAGE_PREFIX=ghcr.io/<org>/<repo> ./deploy/rollback.sh 2.0.3
python apps/api/scripts/smoke.py --base https://<site> --web https://<site> --edge --expect-version <rolled-back version>
```
It pulls the old images, restarts `api worker scheduler web nginx` with `--wait`, records the new `.release`, and swaps `.release.previous` so you can roll *forward* the same way.
The CD pipeline prints this command when its post-deploy smoke test fails.

Expected duration: image pull + restart, about a minute; the API is unavailable for roughly the container restart (≈ 10–15 s for a single instance — measured 12 s including the graceful shutdown). With two API replicas behind nginx there is no gap.

## When the migration is the problem

| Situation | Action |
|---|---|
| The new migration is slow/locking production | stop the deploy; `alembic downgrade -1` only if the migration is the newest and its `downgrade()` is safe (test it on a restored copy first) |
| A **contract** migration (drop/rename/NOT NULL) shipped and broke the old version | do not roll the application back to a version that expects the old shape; fix forward, or restore from backup ([backup-restoration.md](backup-restoration.md)) |
| Data written by the new version confuses the old one | fix forward; if impossible, restore |

## Prevention

* Back up immediately before each deploy (`deploy/backup/backup.sh`).
* Never ship a contract migration in the same release as the code that stops using the old shape.
* The smoke test runs against staging first and must pass before the production approval step.
