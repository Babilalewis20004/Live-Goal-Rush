# Restoring the database from backup

**When.** Data corruption, an accidental delete, a lost volume or host, a bad contract-style migration, or a security incident that needs a known-good state.
**Background and objectives:** `docs/disaster-recovery/backup-restore.md` (RPO/RTO, retention, encryption).

## 0. Decide the scope

* *Lost the whole database / host* → restore **in place** (steps below, onto a fresh Postgres).
* *Need data back from before a mistake, but the database is otherwise healthy* → restore into a **scratch database**, extract what you need, and copy it across. Never restore over a live database to "undo" a small mistake.

## 1. Find the backup

```bash
ls -1t backups/*.dump.enc | head          # newest first; each has a .sha256 beside it
cat backups/.last_success                  # epoch seconds of the last good backup
```
You need `BACKUP_PASSPHRASE` from the secret store (it is deliberately **not** kept with the backups). Offsite copies: whatever `BACKUP_UPLOAD_CMD` shipped them to.

## 2. Prove it restores first (safe; touches nothing live)

```bash
BACKUP_PASSPHRASE=… deploy/backup/restore_verify.sh backups/<file>.dump.enc
```
It checks the checksum, restores into `<db>_restore_check`, compares the Alembic revision and key table row counts with the live database, checks indexes are valid, drops the scratch database, and prints the elapsed time.
Run this on a schedule (daily) — a backup you have never restored is a hope, not a backup.

## 3. Restore for real

```bash
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production"
$C stop api worker scheduler web nginx            # stop writers; leave postgres and redis up
$C exec -T postgres psql -U football -d postgres -c 'DROP DATABASE IF EXISTS football_livescore WITH (FORCE)' -c 'CREATE DATABASE football_livescore'
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in backups/<file>.dump.enc \
  | $C exec -T postgres pg_restore -U football -d football_livescore --no-owner --no-privileges --exit-on-error
$C run --rm -e RUN_MIGRATIONS=1 --no-deps api alembic upgrade head      # bring the schema to the running code's revision
$C up -d --wait
python apps/api/scripts/smoke.py --base https://<site> --web https://<site> --edge
```

## 4. After the restore

1. **Replay erasures.** Users who deleted their accounts since the backup are back. Take the `account.delete` entries from the audit log you saved before restoring (or from the previous day's log export) and re-run erasure for those ids.
2. **Reconcile payments.** Ask the processor to resend webhooks from the backup time onward (idempotent) — subscription state catches up.
3. **Redis needs nothing** (caches rebuild; the queue refills from beat). Clear sessions only if the incident was a credential compromise.
4. Record what happened, the data window lost (RPO actually achieved) and the elapsed time (RTO actually achieved) in the incident notes.

## Measured on this project (2026-10-08, Docker Desktop on Windows, 4 vCPU)

| Data size | Backup | Restore | Full recovery (restore → migrations check → app up → smoke → data verified through the API) |
|---|---|---|---|
| 304 MB (1.2 M rows; 33 MB encrypted dump) | 32 s | 80 s | **134 s** |
| 3 MB (the real synced data only) | 14 s | 55 s (including three verification queries) | — |
