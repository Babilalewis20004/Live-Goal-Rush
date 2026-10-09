#!/usr/bin/env bash
# PostgreSQL backup: dump, encrypt, checksum, verify it is readable, prune old copies, optionally ship offsite.
#
#   BACKUP_PASSPHRASE=... deploy/backup/backup.sh            # run from the repository / deployment directory
#
# Environment:
#   COMPOSE            how to reach the stack      (default: docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production)
#   PG_SERVICE         compose service name        (default: postgres)
#   PG_USER / PG_DB    database credentials        (default: football / football_livescore)
#   BACKUP_DIR         where copies are kept       (default: ./backups)
#   BACKUP_PASSPHRASE  REQUIRED: encrypts the dump (AES-256-CBC + PBKDF2). Keep it in the secret store, NOT with the backups.
#   BACKUP_METRICS_FILE / BACKUP_HEARTBEAT_URL   optional success reporting (see the end of this script)
#   BACKUP_UPLOAD_CMD  optional offsite hook, run with the encrypted file path as $1 (e.g. "aws s3 cp --sse AES256")
#   KEEP_DAILY / KEEP_WEEKLY / KEEP_MONTHLY   retention (default 7 / 4 / 6)
#
# Exit status is non-zero if ANY step fails, so cron / the scheduler can alert on it. A backup that was never
# verified by restoring it is not a backup: run restore_verify.sh on a schedule too (docs/disaster-recovery/).
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production}"
PG_SERVICE="${PG_SERVICE:-postgres}"
PG_USER="${PG_USER:-football}"
PG_DB="${PG_DB:-football_livescore}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${KEEP_MONTHLY:-6}"

: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE must be set (backups are always encrypted)}"
mkdir -p "$BACKUP_DIR"
umask 077

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
base="$BACKUP_DIR/${PG_DB}-${stamp}"
started=$(date +%s)

echo "[backup] dumping $PG_DB (custom format, compressed)"
# -Fc: custom format (selective, parallel restore). Streamed straight into the encryptor, so plaintext never touches disk.
$COMPOSE exec -T "$PG_SERVICE" pg_dump -U "$PG_USER" -d "$PG_DB" -Fc --no-owner --no-privileges \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -out "$base.dump.enc"

size=$(wc -c < "$base.dump.enc")
if [ "$size" -lt 1024 ]; then
  echo "[backup] FAILED: the dump is only $size bytes -- pg_dump produced nothing usable" >&2
  rm -f "$base.dump.enc"
  exit 1
fi

echo "[backup] verifying the file decrypts and the archive is readable"
# 1) the whole file decrypts (a wrong passphrase or a damaged file fails the padding check here)
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$base.dump.enc" > /dev/null
# 2) pg_restore can read its table of contents. It stops reading once it has the TOC, which breaks the pipe for a
#    large archive, so a non-zero exit from the decryptor at that point is expected and ignored.
( set +o pipefail
  openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$base.dump.enc" 2>/dev/null     | $COMPOSE exec -T "$PG_SERVICE" pg_restore --list > "$base.toc" )
tables=$(grep -c "TABLE DATA" "$base.toc" || true)
if [ "$tables" -lt 10 ]; then
  echo "[backup] FAILED: archive lists only $tables tables of data" >&2
  exit 1
fi
rm -f "$base.toc"

( cd "$BACKUP_DIR" && sha256sum "$(basename "$base").dump.enc" > "$(basename "$base").dump.enc.sha256" )

if [ -n "${BACKUP_UPLOAD_CMD:-}" ]; then
  echo "[backup] shipping offsite"
  $BACKUP_UPLOAD_CMD "$base.dump.enc"
  $BACKUP_UPLOAD_CMD "$base.dump.enc.sha256"
fi

# -- retention: newest N daily, one per ISO week for N weeks, one per month for N months --------------------------------
prune() {
  python3 - "$BACKUP_DIR" "$KEEP_DAILY" "$KEEP_WEEKLY" "$KEEP_MONTHLY" <<'PY'
import os, re, sys
from datetime import datetime
directory, daily, weekly, monthly = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
files = sorted(f for f in os.listdir(directory) if re.search(r"-\d{8}T\d{6}Z\.dump\.enc$", f))
stamped = [(datetime.strptime(re.search(r"(\d{8}T\d{6}Z)", f).group(1), "%Y%m%dT%H%M%SZ"), f) for f in files]
stamped.sort(reverse=True)
keep = {f for _, f in stamped[:daily]}
seen_weeks, seen_months = set(), set()
for ts, f in stamped:
    week, month = ts.strftime("%G-%V"), ts.strftime("%Y-%m")
    if week not in seen_weeks and len(seen_weeks) < weekly:
        seen_weeks.add(week); keep.add(f)
    if month not in seen_months and len(seen_months) < monthly:
        seen_months.add(month); keep.add(f)
for _, f in stamped:
    if f not in keep:
        for suffix in ("", ".sha256"):
            path = os.path.join(directory, f + suffix)
            if os.path.exists(path):
                os.remove(path)
                print(f"[backup] pruned {f}{suffix}")
PY
}
prune

# Success is reported three ways, so a stale backup is noticed whichever monitoring you run:
#   1. a file next to the backups               2. a metric for node-exporter's textfile collector (alert: BackupStale)
#   3. an HTTP "dead man's switch" ping (healthchecks.io style) that alerts when the ping STOPS arriving
date +%s > "$BACKUP_DIR/.last_success"
if [ -n "${BACKUP_METRICS_FILE:-}" ]; then
  printf '# TYPE backup_last_success_timestamp_seconds gauge
backup_last_success_timestamp_seconds %s
# TYPE backup_last_size_bytes gauge
backup_last_size_bytes %s
' "$(date +%s)" "$size" > "$BACKUP_METRICS_FILE.tmp"     && mv "$BACKUP_METRICS_FILE.tmp" "$BACKUP_METRICS_FILE"
fi
[ -n "${BACKUP_HEARTBEAT_URL:-}" ] && curl -fsS -m 10 --retry 3 "$BACKUP_HEARTBEAT_URL" > /dev/null || true

echo "[backup] OK ${base}.dump.enc ($(( size / 1024 )) KiB) in $(( $(date +%s) - started ))s"
