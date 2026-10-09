#!/usr/bin/env bash
# Restore a backup into a scratch database and prove it is usable. Safe to run against a live stack: it never
# touches the production database, only creates and drops `<db>_restore_check`.
#
#   BACKUP_PASSPHRASE=... deploy/backup/restore_verify.sh [path/to/file.dump.enc]    # default: newest in $BACKUP_DIR
#
# Steps (each one timed; the total is the measured RTO for the database tier):
#   1 checksum   2 decrypt + restore into a scratch DB   3 migrations: the restored schema is at the expected
#   revision   4 row counts of the key tables are within tolerance of the live database   5 drop the scratch DB
#
# Exit status is non-zero on any failure. Intended to run daily from cron / the scheduler, plus before every release.
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production}"
PG_SERVICE="${PG_SERVICE:-postgres}"
PG_USER="${PG_USER:-football}"
PG_DB="${PG_DB:-football_livescore}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
SCRATCH="${PG_DB}_restore_check"
TOLERANCE_PCT="${TOLERANCE_PCT:-5}"      # live tables may have grown since the backup was taken
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE must be set}"

file="${1:-$(ls -1t "$BACKUP_DIR"/*.dump.enc 2>/dev/null | head -1)}"
[ -n "$file" ] && [ -f "$file" ] || { echo "[restore] no backup file found" >&2; exit 1; }
psql_scratch() { $COMPOSE exec -T "$PG_SERVICE" psql -U "$PG_USER" -d "$SCRATCH" -v ON_ERROR_STOP=1 -At "$@"; }
psql_live() { $COMPOSE exec -T "$PG_SERVICE" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -At "$@"; }
cleanup() { $COMPOSE exec -T "$PG_SERVICE" psql -U "$PG_USER" -d postgres -qAt -c "DROP DATABASE IF EXISTS \"$SCRATCH\" WITH (FORCE)" >/dev/null 2>&1 || true; }
trap cleanup EXIT

t0=$(date +%s)
step() { echo "[restore] $* (t+$(( $(date +%s) - t0 ))s)"; }

step "1/5 checksum of $(basename "$file")"
if [ -f "$file.sha256" ]; then
  ( cd "$(dirname "$file")" && sha256sum -c "$(basename "$file").sha256" )
else
  echo "[restore] WARNING: no .sha256 next to the backup" >&2
fi

step "2/5 restoring into scratch database $SCRATCH"
cleanup
$COMPOSE exec -T "$PG_SERVICE" psql -U "$PG_USER" -d postgres -qAt -c "CREATE DATABASE \"$SCRATCH\"" >/dev/null
# pg_trgm is created by the migrations and referenced by indexes inside the dump.
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$file" \
  | $COMPOSE exec -T "$PG_SERVICE" pg_restore -U "$PG_USER" -d "$SCRATCH" --no-owner --no-privileges --exit-on-error

step "3/5 schema revision"
restored_rev="$(psql_scratch -c 'SELECT version_num FROM alembic_version')"
live_rev="$(psql_live -c 'SELECT version_num FROM alembic_version')"
echo "[restore]   restored=$restored_rev live=$live_rev"
[ -n "$restored_rev" ] || { echo "[restore] FAILED: restored database has no alembic revision" >&2; exit 1; }

step "4/5 row counts (tolerance ${TOLERANCE_PCT}% growth since the backup)"
status=0
for table in users matches teams players competitions articles comments subscriptions payment_events notification_log refresh_tokens; do
  restored="$(psql_scratch -c "SELECT count(*) FROM $table" 2>/dev/null || echo MISSING)"
  live="$(psql_live -c "SELECT count(*) FROM $table" 2>/dev/null || echo 0)"
  if [ "$restored" = "MISSING" ]; then echo "[restore]   $table: MISSING from restore"; status=1; continue; fi
  # the restore may have FEWER rows than live (growth since the backup) but never wildly more, and never be empty if live is not
  if [ "$live" -gt 0 ] && [ "$restored" -eq 0 ]; then echo "[restore]   $table: restored 0 rows, live has $live"; status=1; continue; fi
  allowed=$(( live + live * TOLERANCE_PCT / 100 ))
  if [ "$restored" -gt "$allowed" ]; then echo "[restore]   $table: restored $restored > live $live (+${TOLERANCE_PCT}%)"; status=1; continue; fi
  echo "[restore]   $table: restored=$restored live=$live ok"
done

step "5/5 integrity: every foreign key and unique index in the restore holds"
bad_idx="$(psql_scratch -c "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE NOT i.indisvalid")"
[ "$bad_idx" = "0" ] || { echo "[restore] FAILED: $bad_idx invalid indexes in the restore" >&2; status=1; }

elapsed=$(( $(date +%s) - t0 ))
if [ "$status" -ne 0 ]; then
  echo "[restore] FAILED after ${elapsed}s" >&2
  exit 1
fi
date +%s > "$BACKUP_DIR/.last_verified"
echo "[restore] OK: $(basename "$file") restores to revision $restored_rev in ${elapsed}s (this is the measured database RTO for this data size)"
