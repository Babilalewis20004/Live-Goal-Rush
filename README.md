# LivePitch — Real-Time Football Livescore Platform

A football-only livescore platform inspired by apps like LiveScore, SofaScore
and Flashscore — with its own branding, architecture and implementation.
Phase 1 delivered a working, provider-agnostic MVP. **Phase 2 makes it
real-time**: when a match changes, connected web and mobile clients see it
without refreshing — via a Redis-backed cache/messaging layer, a Celery
background sync pipeline with adaptive polling, change detection, and
WebSocket push.

## Features

**Phase 1** — Live, today's, and upcoming matches, plus finished results,
grouped by competition; match details (score, status, kickoff, venue,
half-time score, full event timeline); competition pages (fixtures +
standings); team pages (fixtures + results); global search; loading/empty/
error states everywhere; web (Next.js) and mobile (Expo) clients sharing
one API contract.

**Phase 2** —

- Redis cache-aside reads in front of PostgreSQL for every high-read
  endpoint, with documented, non-arbitrary TTLs
- A Celery worker + scheduler doing background provider synchronization
  with **adaptive polling** (live matches polled far more often than
  scheduled/finished ones — never every match, all the time)
- Change detection: only a *meaningful* change (score, status, minute, a
  new event) triggers a broadcast — not every poll
- Redis Pub/Sub bridging the worker to a WebSocket layer
  (`/ws/matches`, `/ws/matches/{id}`) that pushes updates to web and
  mobile clients in real time
- Client-side reconnection with exponential backoff + a REST resync on
  reconnect, on both web and mobile (with app-lifecycle-aware connection
  handling on mobile)
- Stale-data detection (`data_status`: `FRESH`/`STALE`/`UNAVAILABLE`) on
  every match response
- Graceful degradation on provider or Redis outages — the app keeps
  serving the most recent known data rather than crashing or fabricating
  updates
- Idempotent, deduplicated background sync jobs; structured logging;
  basic metrics (`/metrics`) and a dependency-aware `/health`
- The bundled mock provider's "live" fixtures now progress in real time
  (see `docs/architecture/realtime.md`), so the whole pipeline is
  observable end-to-end without any external API credentials

## Architecture

```
Football Data Provider (mock, time-evolving — or a real API like football-data.org)
        │
        ▼
Celery worker  ◄── Celery beat (scheduler)
        │  sync + change detection + Redis Pub/Sub publish
        ▼
PostgreSQL (durable)         Redis (cache-aside + Pub/Sub)
        │                            │
        └─────────────┬──────────────┘
                       ▼
                FastAPI (/api/v1 cache-aside reads, /ws/* WebSocket push)
                       │
        ┌──────────────┼──────────────┐
        ▼                             ▼
      Web (Next.js)                Mobile (Expo)
```

Full write-ups:
[system-architecture.md](docs/architecture/system-architecture.md) ·
[data-flow.md](docs/architecture/data-flow.md) ·
[database.md](docs/architecture/database.md) ·
[api-architecture.md](docs/architecture/api-architecture.md) ·
[realtime.md](docs/architecture/realtime.md) ·
[caching.md](docs/architecture/caching.md) ·
[background-workers.md](docs/development/background-workers.md) ·
[websockets.md](docs/development/websockets.md) ·
[docker.md](docs/deployment/docker.md)

## Monorepo structure

```
apps/
  api/      FastAPI backend + Celery worker/scheduler
  web/      Next.js web app
  mobile/   Expo React Native app
packages/
  shared/   Hand-synced TypeScript type reference (see its header comment)
docs/
  architecture/
  development/
  deployment/
docker-compose.yml
.env.example
```

## Technology stack

| Layer      | Stack                                                              |
| ---------- | ------------------------------------------------------------------- |
| Backend    | Python, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic, PostgreSQL, httpx, pytest |
| Real-time  | Redis (cache + Pub/Sub), Celery (worker + beat scheduler), WebSockets (FastAPI/Starlette) |
| Web        | Next.js 16 (App Router), TypeScript, React 19, Tailwind CSS v4, Vitest |
| Mobile     | Expo SDK 57, React Native, Expo Router, TypeScript                  |
| Infra      | Docker, Docker Compose                                              |

## Quickest start: Docker Compose (everything)

```bash
cp .env.example .env   # override POSTGRES_PORT/REDIS_PORT if already taken
docker compose up --build
```

Starts `postgres`, `redis`, `api` (runs migrations, then serves), `worker`,
`scheduler`, and `web`. API: http://localhost:8000 (`/docs`, `/health`,
`/metrics`). Web: http://localhost:3000. Full details, including why
`worker`/`scheduler` wait on `api`'s healthcheck specifically:
[docs/deployment/docker.md](docs/deployment/docker.md).

`apps/mobile` isn't containerized (native/Expo tooling doesn't fit a
Compose service well) — run it locally (below), pointed at the Dockerized
API.

## Running each app locally (without Docker)

### 1. Backend (`apps/api`)

Needs a reachable PostgreSQL and Redis (either via `docker compose up
postgres redis`, or your own local installs).

```bash
cd apps/api
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # edit DATABASE_URL/REDIS_URL if not using the defaults
alembic upgrade head
uvicorn app.main:app --reload
```

For real-time updates to actually flow, also run the worker and scheduler
(separate terminals, same venv/`.env`):

```bash
celery -A app.worker.celery_app worker --loglevel=info --concurrency=2
celery -A app.worker.celery_app beat --loglevel=info
```

(On Windows outside Docker, add `--pool=solo` to the worker command if you
hit Celery's known prefork issues there — Docker Compose doesn't need this.)

Run the test suite (needs a reachable Postgres — the same one `DATABASE_URL`
points at; a `_test`-suffixed database is created automatically; Redis is
faked in-process via `fakeredis`, no real Redis needed for tests):

```bash
pytest
```

### 2. Web app (`apps/web`)

```bash
cd apps/web
npm install
cp .env.example .env.local 2>/dev/null || printf "NEXT_PUBLIC_API_URL=http://localhost:8000\nNEXT_PUBLIC_WS_URL=ws://localhost:8000\n" > .env.local
npm run dev
```

Open http://localhost:3000. Other scripts: `npm run build`, `npm start`,
`npm run lint`, `npm run typecheck`, `npm test`.

### 3. Mobile app (`apps/mobile`)

```bash
cd apps/mobile
npm install
cp .env.example .env   # EXPO_PUBLIC_API_URL/EXPO_PUBLIC_WS_URL — use your
                        # machine's LAN IP, not localhost, on a physical device
npx expo start
```

Scan the QR code with Expo Go, or press `i`/`a` for a simulator. Other
scripts: `npx tsc --noEmit`, `npx expo lint`.

## Environment variables

See [.env.example](.env.example) (repo root, used by Docker Compose) and the
per-app `.env.example` files in `apps/api`, `apps/web`, `apps/mobile`. Never
commit a real `.env` file or real credentials.

| Variable                       | Used by        | Purpose                                              |
| -------------------------------- | -------------- | ----------------------------------------------------- |
| `DATABASE_URL`                   | api, worker, scheduler | Postgres connection string (asyncpg driver) |
| `REDIS_URL`                      | api, worker, scheduler | Redis connection string (cache + Pub/Sub) |
| `FOOTBALL_DATA_PROVIDER`         | api, worker, scheduler | `mock` (default) or `real`                  |
| `FOOTBALL_API_BASE_URL` / `FOOTBALL_API_KEY` | api, worker, scheduler | Real provider config (only if `FOOTBALL_DATA_PROVIDER=real`) |
| `CORS_ORIGINS`                   | api            | Comma-separated allow-list — also gates WebSocket origins |
| `LIVE_POLL_INTERVAL_SECONDS` / `UPCOMING_POLL_INTERVAL_SECONDS` / `POST_MATCH_SYNC_INTERVAL_SECONDS` | worker, scheduler | Adaptive polling intervals |
| `REDIS_LIVE_MATCH_TTL_SECONDS` / `REDIS_DEFAULT_TTL_SECONDS` | api | Cache TTLs |
| `WEBSOCKET_HEARTBEAT_SECONDS` / `WEBSOCKET_MAX_CONNECTIONS` | api | WebSocket heartbeat + connection cap |
| `SYNC_MAX_RETRIES` / `SYNC_BACKOFF_SECONDS` | worker | Provider retry/backoff |
| `MOCK_LIVE_SECONDS_PER_MINUTE`   | api, worker    | Mock provider's simulated live-match speed |
| `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` | web | REST / WebSocket base URLs |
| `EXPO_PUBLIC_API_URL` / `EXPO_PUBLIC_WS_URL` | mobile | REST / WebSocket base URLs |

Full documentation (defaults, TTL strategy, polling rationale) in
`apps/api/.env.example`, `docs/architecture/caching.md`, and
`docs/architecture/realtime.md`.

## Activating a real football data provider

Ships with `MockFootballDataProvider` (deterministic, no external calls,
now with time-evolving live matches — see `docs/architecture/realtime.md`)
because no real API credentials are available in this environment.
`RealFootballDataProvider` (`apps/api/app/services/providers/real_provider.py`)
targets football-data.org's free-tier v4 API as a concrete example, behind
the exact same `FootballDataProvider` interface. To activate it:

1. Get a free key at https://www.football-data.org/client/register
2. Set `FOOTBALL_DATA_PROVIDER=real`, `FOOTBALL_API_BASE_URL=https://api.football-data.org/v4`,
   and `FOOTBALL_API_KEY=<your key>`
3. Restart the API/worker/scheduler — no other code changes required

The free tier's coverage/rate limits are narrower than the mock dataset and
it has no event timeline or unified search endpoint; see the comments in
`real_provider.py`, and lower `LIVE_POLL_INTERVAL_SECONDS` accordingly (see
`docs/architecture/realtime.md`'s provider rate-limit section) — its default
assumes the generous mock provider, not a rate-limited free tier.

## Database

SQLAlchemy 2.x models for `Competition`, `Team`, `Player`, `Match`,
`MatchEvent`, and (Phase 2) `Standing`, with indexes on provider IDs,
competition/team foreign keys, kickoff time, and match status. Alembic
manages migrations (`apps/api/alembic/`); `alembic upgrade head`
initializes a fresh database from scratch, including Phase 2's schema.
Details: [docs/architecture/database.md](docs/architecture/database.md).
Redis is a cache + messaging layer only — never the source of truth; see
[docs/architecture/caching.md](docs/architecture/caching.md).

## API

Versioned REST API under `/api/v1` — matches, competitions, teams, and
search — plus `/ws/matches` and `/ws/matches/{id}` for real-time push.
Full interactive REST docs at `/docs` (Swagger UI) once the API is running.
Details: [docs/architecture/api-architecture.md](docs/architecture/api-architecture.md),
[docs/architecture/realtime.md](docs/architecture/realtime.md).

## Testing

- Backend: `cd apps/api && pytest` — covers the mock provider (including
  its time-evolving live-match simulation), the service layer's cache-aside
  reads, all REST endpoints, pagination/error/validation handling, the
  Redis service and cache-aside layer, change detection, event
  idempotency/dedup, provider retry/backoff, and the WebSocket connection
  manager + endpoints.
- Web: `cd apps/web && npx tsc --noEmit && npx eslint . && npm test` —
  `npm test` (Vitest) covers the WebSocket client's reconnect/backoff/
  heartbeat behavior and the real-time hooks' pure update logic (applying
  an incoming message, deriving live/today/upcoming/finished views).
- Mobile: `cd apps/mobile && npx tsc --noEmit && npx expo lint` — mirrors
  web's hooks/client by construction (same contract, parallel
  implementation); no separate React Native test harness was added in
  Phase 2 (see Known limitations).

## Roadmap (Phase 3+)

Deliberately out of scope for Phase 2, but the architecture (adaptive
polling, change detection, Pub/Sub, cache-aside reads) is designed not to
need a rewrite for these:

- Push notifications (goal alerts, match start/finish) — the event model
  (`app/events/schemas.py`) is already the natural source for these
- Advanced match statistics (possession, shots, xG) and player statistics
- User accounts + WebSocket authentication (the connection layer is
  already structured with an auth check extension point)
- Cross-process metrics aggregation (Prometheus multiprocess mode) instead
  of per-process-only `/metrics`
- Betting odds, advertisements, subscriptions/payments
- Social features, AI features, chat
- A real automated type-sharing pipeline between the FastAPI schemas and
  the TypeScript clients (e.g. `openapi-typescript`), replacing the
  hand-synced `packages/shared/types.ts` (now including the WebSocket
  message contract too)
- A React Native test harness for the mobile hooks (currently verified by
  typecheck/lint + manual testing, matching web's hook contract by
  construction — see Known limitations)

## Known limitations

- Dynamic not-found pages on the web app (invalid match/competition/team id)
  render the correct UI but return HTTP 200 instead of 404, per documented
  Next.js App Router streaming behavior (a `noindex` meta tag is injected as
  a mitigation). See the web app's git history for details.
- Kickoff times are displayed in UTC, not the viewer's local timezone.
- The mobile app's web-export target (used only for automated verification
  in this environment, not a real target platform) shows a React hydration
  console warning on the search screen; iOS/Android are unaffected.
- No automated React Native component/hook tests (Phase 2 added Vitest
  coverage for the web app's equivalent logic; the mobile hooks mirror it
  by construction and are covered by typecheck/lint + manual testing).
- Per-process metrics only (`/metrics` on the API process reports its own
  cache/WebSocket counters; the worker's provider/sync counters are
  visible in its logs, not yet aggregated into one scrape target) — see
  `app/services/metrics.py`'s docstring and the Roadmap.
- The mock provider's simulated live-match progression (real time, ~2s per
  simulated minute by default) means kickoff times reported for "live"
  fixtures drift from wall-clock reality the longer a process runs — a
  deliberate trade-off for having *something* to demo in real time without
  a real provider; see `docs/architecture/realtime.md`.
