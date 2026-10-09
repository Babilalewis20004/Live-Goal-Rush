#!/usr/bin/env bash
# Roll the application back to the previously deployed release.
#
#   cd /opt/livepitch && ./deploy/rollback.sh            # to the release recorded in .release.previous
#   ./deploy/rollback.sh 2.0.3                           # to a named release
#
# Application rollback does NOT touch the database. That is safe because every migration is expand-only (new tables,
# nullable columns, new indexes; see docs/deployment/migrations.md), so the previous version runs against the newer
# schema. If a release shipped a contract (destructive) migration, restore from backup instead:
# docs/runbooks/rollback.md.
set -euo pipefail
cd "$(dirname "$0")/.."

target="${1:-$(cat .release.previous 2>/dev/null || true)}"
[ -n "$target" ] && [ "$target" != "none" ] || { echo "no previous release recorded; pass a version" >&2; exit 1; }
current="$(cat .release 2>/dev/null || echo unknown)"
: "${IMAGE_PREFIX:?set IMAGE_PREFIX, e.g. ghcr.io/org/repo}"

echo "rolling back $current -> $target"
export APP_VERSION="$target" API_IMAGE="$IMAGE_PREFIX-api:$target" WEB_IMAGE="$IMAGE_PREFIX-web:$target"
compose="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.release.yml --env-file .env.production"
$compose pull api web
RUN_MIGRATIONS=0 $compose up -d --no-build --no-deps --wait api worker scheduler web nginx
echo "$target" > .release
echo "$current" > .release.previous
echo "rolled back to $target; verify with: python apps/api/scripts/smoke.py --base \$PUBLIC_ORIGIN --expect-version $target"
