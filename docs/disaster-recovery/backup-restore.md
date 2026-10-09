# Backups, restore and recovery objectives

## What is backed up

| Data | Mechanism | Frequency | Retention | Encrypted | Where |
|---|---|---|---|---|---|
| PostgreSQL (system of record) | `deploy/backup/backup.sh` — `pg_dump -Fc` streamed through `openssl enc -aes-256-cbc -pbkdf2` | **daily** (cron below); also before every deploy | 7 daily · 4 weekly · 6 monthly (`KEEP_*`) | yes — passphrase in the secret store, never beside the files | local `./backups` **and** an offsite copy via `BACKUP_UPLOAD_CMD` (e.g. `aws s3 cp --sse AES256` to a separate account) |
| Redis | not backed up — caches, counters, queue; recreated | AOF on for restart safety only | — | — | — |
| Uploaded images | object storage (S3/R2) — enable bucket versioning and cross-region replication at the provider | provider | provider | provider | the bucket |
| Secrets / `.env.production` | your secret manager | — | — | — | — |
| Application | git + container registry | every release | tagged versions | — | — |

`backup.sh` fails (non-zero) if the dump is empty, the file does not decrypt, `pg_restore --list` cannot read it, or fewer than 10 tables of data are listed — it writes
`.last_success`, an optional metric (`BACKUP_METRICS_FILE`) and an optional dead-man's-switch ping (`BACKUP_HEARTBEAT_URL`).

```cron
# /etc/cron.d/livepitch-backup  — 02:15 UTC daily; verify restore at 03:00
15 2 * * *  deploy  cd /opt/livepitch && BACKUP_PASSPHRASE="$(cat /run/secrets/backup_passphrase)" BACKUP_METRICS_FILE=/var/lib/node_exporter/textfile/backup.prom BACKUP_HEARTBEAT_URL=https://hc-ping.com/<uuid> BACKUP_UPLOAD_CMD="aws s3 cp --sse AES256" deploy/backup/backup.sh >> /var/log/livepitch-backup.log 2>&1
0 3 * * *   deploy  cd /opt/livepitch && BACKUP_PASSPHRASE="$(cat /run/secrets/backup_passphrase)" deploy/backup/restore_verify.sh >> /var/log/livepitch-backup.log 2>&1
```

## Restore is tested, not assumed

`deploy/backup/restore_verify.sh` restores the newest backup into a scratch database, checks the checksum, the Alembic revision, row counts of eleven key tables against the live database (tolerating growth), and index validity, then drops the scratch database. It was run on 2026-10-08:

| Dataset | Dump (encrypted) | Backup time | Restore + checks | Result |
|---|---|---|---|---|
| real synced data (8 users, 1,140 matches, 1,672 players) | 489 KiB | 14 s | 57 s | all tables matched |
| 304 MB synthetic (20 k users, 440 k comments, 609 k ledger rows, 80 k sessions) | 33 MB | 32 s | 100 s | all 11 tables matched exactly; a **wrong passphrase failed loudly** |

### Full recovery drill (2026-10-08)

Simulated total loss: created an empty database, restored the encrypted backup, ran the migrations check, started the API against it, ran the smoke test and read the data back through the API.

| Step | Elapsed |
|---|---|
| empty database created | 3 s |
| data restored from the encrypted backup (304 MB database) | 83 s |
| migrations checked (already at head) | 88 s |
| application started and **ready** | 122 s |
| smoke test finished | 127 s |
| data verified through the API (440,269 comments, 351 in a thread) | **134 s** |

The only smoke check that failed was the cosmetic "no server banner" one, because the drill ran uvicorn directly instead of the production image (which passes `--no-server-header`).

## Recovery objectives (what is honestly achievable with this architecture)

| | Objective | Basis |
|---|---|---|
| **RPO — PostgreSQL** | **24 hours** with the daily dump (up to 24 h of comments, sign-ups, subscriptions lost); **≤ 1 hour** if the cron runs hourly (the dump takes ≈ 30 s for 300 MB, so hourly is affordable up to a few GB). Not zero. | Logical backups only. WAL archiving / point-in-time recovery would give an RPO of minutes; it is **not configured** and is the recommended next step (or use a managed Postgres, which includes it). |
| **RPO — payments** | ≈ 0 for money: the payment processor is the record, webhooks are retried by it, and processing is idempotent; subscription state catches up after a restore by replaying events | `docs/runbooks/payment-webhook-failure.md` |
| **RTO — application only** (bad release) | ≈ 1–2 minutes (`deploy/rollback.sh`) | measured restart ≈ 12 s per instance |
| **RTO — data store lost** | **≈ 3–5 minutes for the restore itself at 300 MB** (measured 134 s end to end); allow 15–30 minutes including finding the backup, the passphrase and a host. Scales roughly linearly with size: ≈ 80 s per 300 MB restored on this hardware, plus index builds | the drill above |
| **RTO — host lost** | provisioning time + the restore: ≈ 30–60 minutes with a prepared runbook and an infrastructure image | not drilled; depends on your provider |
| **Redis lost** | ≈ 0 — nothing to restore; reads continue from Postgres | `docs/operations/redis.md` |

These are **targets backed by one measured drill on development hardware with a synthetic dataset**, not guarantees. Re-run the drill on staging with production-sized data before launch and replace the numbers (checklist item).

## Known limitations

* Backups, restore and erasure: users erased since a backup reappear after restoring it — replay the erasures (`docs/runbooks/backup-restoration.md`).
* The backup passphrase is a single symmetric secret; lose it and every backup is unreadable. Store it in two places (secret manager + sealed offline copy).
* `pg_dump` takes a consistent snapshot without blocking writers, but it is a *logical* dump: restore time grows with indexes and data, not just file size.
* Only one backup host/process exists; the cron job itself is a single point of failure — hence the dead-man's-switch ping.
