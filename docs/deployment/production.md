# Deploying to production

The production topology is the Docker Compose stack in `docker-compose.yml` plus the overlay `docker-compose.prod.yml`,
fronted by nginx. It runs on one Docker host (or several, behind a load balancer); nothing here needs an orchestrator.
Architecture and scaling units: `docs/architecture/production-architecture.md`.

## What the production overlay changes

| Concern | Development (`docker-compose.yml`) | Production (`+ docker-compose.prod.yml`) |
|---|---|---|
| Published ports | api 8000, web 3000, postgres, redis, minio, … | **only nginx** (`HTTP_PORT`, default 80); Prometheus/Grafana on 127.0.0.1 |
| Secrets | insecure defaults so it boots | **required** — compose refuses to start if one is unset |
| `ENVIRONMENT` | `development` | `production` — enables startup validation, docs off, secure cookies, HSTS |
| Redis | open, no limits | password, 256 MB cap, `volatile-lru` (never evicts the Celery queue), AOF |
| Media | MinIO container | a real S3-compatible bucket (MinIO is behind the `local-only` profile) |
| Reverse proxy | none | nginx (unprivileged, read-only filesystem, no capabilities) |
| Restart policy | none | `unless-stopped` |

## First deployment

1. **Provision** a host with Docker 24+ and compose v2.24+ (the overlay uses `!reset`/`!override`). Open 80/443 only.
2. **TLS.** Terminate it in front of nginx (a cloud load balancer, Caddy, or Cloudflare). nginx listens on plain HTTP
   inside the private network and trusts `X-Forwarded-Proto` from that terminator. Set `HSTS` preload only once you are sure.
   If a load balancer sits in front, add `set_real_ip_from <LB CIDR>; real_ip_header X-Forwarded-For;` to the `http` block of
   `deploy/nginx/nginx.conf` so the client address the API sees is the visitor's, not the balancer's.
3. **Secrets.** `cp .env.production.example .env.production` and fill it in (never commit it; it is git-ignored).
   Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. See `docs/deployment/environments.md`
   for what every variable does.
4. **Validate before starting** — the API will refuse to boot on an unsafe configuration, but find out first:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production config -q
   ```
5. **Build or pull images, migrate, start:**

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production build
   docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d --wait postgres redis
   # migrations run once, before any new code serves traffic (docs/deployment/migrations.md)
   docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production run --rm -e RUN_MIGRATIONS=1 --no-deps api alembic upgrade head
   RUN_MIGRATIONS=0 docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d --wait
   ```
6. **Grant the first administrator** (there is deliberately no API for granting roles):
   `docker compose … exec api python -m app.cli set-role you@example.com admin`
7. **Smoke test** the public origin: `python apps/api/scripts/smoke.py --base https://livepitch.example --web https://livepitch.example --edge`
8. **Schedule backups** and verify one restores (`docs/disaster-recovery/backup-restore.md`), then wire the alerts
   (`docs/operations/observability.md`). Work through `docs/production-launch-checklist.md`.

## Scaling the API

`WEB_CONCURRENCY=4` (uvicorn workers per container) is the first lever; each worker holds its own connection pool, so
keep `(DB_POOL_SIZE + DB_MAX_OVERFLOW) × workers × containers + Celery processes × pool` below Postgres'
`max_connections`. Sizing guidance and thresholds are in `docs/operations/capacity.md`.

## Day-two commands

```bash
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production"
$C ps                                   # health of every service
$C logs -f --tail 200 api               # JSON logs, one object per line; grep by request_id
curl -s localhost/version               # what is running
$C exec api python -m app.cli set-role user@example.com editor
$C run --rm -e RUN_MIGRATIONS=1 --no-deps api alembic current
```

Release, rollback and the CI/CD pipeline: `docs/deployment/ci-cd.md`. Runbooks for when something breaks:
`docs/runbooks/`.
