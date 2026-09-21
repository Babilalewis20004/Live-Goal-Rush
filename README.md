# LivePitch — Football Livescore Platform (Phase 1 MVP)

A football-only livescore platform inspired by apps like LiveScore, SofaScore
and Flashscore — with its own branding, architecture and implementation.
Phase 1 delivers a working, provider-agnostic MVP: a FastAPI backend behind a
football-data provider abstraction (mock provider by default), a Next.js web
app, and a functional Expo/React Native mobile app, all sharing one API
contract.

## Features (Phase 1)

- Live, today's, and upcoming matches, plus finished results, grouped by
  competition
- Match details: score, status, kickoff time, venue, half-time score, and a
  full event timeline (goals, cards, subs)
- Competition pages: fixtures and a standings table
- Team pages: upcoming fixtures and recent results
- Global search across teams, competitions and players
- Loading, empty, and error states everywhere — no blank screens, no raw
  stack traces
- Web (Next.js) and mobile (Expo) clients consuming the exact same API

## Architecture

```
Football Data Provider (mock, or a real API like football-data.org)
        │
        ▼
Provider Adapter (FootballDataProvider interface)
        │
        ▼
Normalization (provider DTOs → internal domain shapes)
        │
        ▼
Service Layer (FootballService — syncs provider data into Postgres,
                serves every read from the database)
        │
        ▼
PostgreSQL (SQLAlchemy 2.x models, Alembic migrations)
        │
        ▼
FastAPI (/api/v1 — versioned REST API, OpenAPI docs at /docs)
        │
   ┌────┴────┐
   ▼         ▼
 Web       Mobile
(Next.js)  (Expo / React Native)
```

Full write-ups: [docs/architecture/system-architecture.md](docs/architecture/system-architecture.md),
[data-flow.md](docs/architecture/data-flow.md),
[database.md](docs/architecture/database.md),
[api-architecture.md](docs/architecture/api-architecture.md).

## Monorepo structure

```
apps/
  api/      FastAPI backend
  web/      Next.js web app
  mobile/   Expo React Native app
packages/
  shared/   Hand-synced TypeScript type reference (see its header comment)
docs/
  architecture/
docker-compose.yml
.env.example
```

## Technology stack

| Layer      | Stack                                                              |
| ---------- | ------------------------------------------------------------------- |
| Backend    | Python, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic, PostgreSQL, httpx, pytest |
| Web        | Next.js 16 (App Router), TypeScript, React 19, Tailwind CSS v4      |
| Mobile     | Expo SDK 57, React Native, Expo Router, TypeScript                  |
| Infra      | Docker, Docker Compose                                              |

## Local setup

### Prerequisites

- Node.js 20.9+ and npm
- Python 3.12+
- PostgreSQL 16 (or Docker, see below)
- (Mobile only) Expo Go app on a phone, or an iOS/Android simulator

### 1. Backend (`apps/api`)

```bash
cd apps/api
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # edit DATABASE_URL if not using the defaults
alembic upgrade head
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs · Health check: http://localhost:8000/health

Run the test suite (needs a reachable Postgres — the same one `DATABASE_URL`
points at; a `_test`-suffixed database is created automatically):

```bash
pytest
```

### 2. Web app (`apps/web`)

```bash
cd apps/web
npm install
cp .env.example .env.local 2>/dev/null || echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

Open http://localhost:3000. Other scripts: `npm run build`, `npm start`,
`npm run lint`, `npm run typecheck`.

### 3. Mobile app (`apps/mobile`)

```bash
cd apps/mobile
npm install
cp .env.example .env   # EXPO_PUBLIC_API_URL — use your machine's LAN IP,
                        # not localhost, when testing on a physical device
npx expo start
```

Scan the QR code with Expo Go, or press `i`/`a` for a simulator. Other
scripts: `npx tsc --noEmit`, `npx expo lint`.

## Docker Compose (all three services)

```bash
cp .env.example .env   # override POSTGRES_PORT if 5432 is already taken
docker compose up --build
```

This builds and starts `postgres`, `api` (runs `alembic upgrade head` before
serving), and `web`. The API is on http://localhost:8000, the web app on
http://localhost:3000. Stop with `docker compose down` (add `-v` to also
drop the Postgres volume).

The `apps/mobile` app isn't containerized (native/Expo tooling doesn't fit a
Docker Compose service well) — run it locally per above, pointed at the
Dockerized API via `EXPO_PUBLIC_API_URL`.

## Environment variables

See [.env.example](.env.example) (repo root, used by Docker Compose) and the
per-app `.env.example` files in `apps/api`, `apps/web`, `apps/mobile`. Never
commit a real `.env` file or real credentials.

Key variables:

| Variable                 | Used by       | Purpose                                              |
| ------------------------- | -------------- | ----------------------------------------------------- |
| `DATABASE_URL`             | api            | Postgres connection string (asyncpg driver)           |
| `FOOTBALL_DATA_PROVIDER`   | api            | `mock` (default) or `real`                            |
| `FOOTBALL_API_BASE_URL`    | api            | Real provider base URL (only if `FOOTBALL_DATA_PROVIDER=real`) |
| `FOOTBALL_API_KEY`         | api            | Real provider API key (never committed)               |
| `CORS_ORIGINS`             | api            | Comma-separated list of allowed origins               |
| `NEXT_PUBLIC_API_URL`      | web            | Base URL the web app fetches from                     |
| `EXPO_PUBLIC_API_URL`      | mobile         | Base URL the mobile app fetches from                  |

## Activating a real football data provider

Phase 1 ships with `MockFootballDataProvider` (deterministic, no external
calls) because no real API credentials are available in this environment.
`RealFootballDataProvider` (`apps/api/app/services/providers/real_provider.py`)
targets football-data.org's free-tier v4 API as a concrete example, behind
the exact same `FootballDataProvider` interface. To activate it:

1. Get a free key at https://www.football-data.org/client/register
2. Set `FOOTBALL_DATA_PROVIDER=real`, `FOOTBALL_API_BASE_URL=https://api.football-data.org/v4`,
   and `FOOTBALL_API_KEY=<your key>`
3. Restart the API — no other code changes required

The free tier's coverage/rate limits are narrower than the mock dataset and
it has no event timeline or unified search endpoint; see the comments in
`real_provider.py` for specifics.

## Database

SQLAlchemy 2.x models for `Competition`, `Team`, `Player`, `Match`, and
`MatchEvent`, with indexes on provider IDs, competition/team foreign keys,
kickoff time, and match status. Alembic manages migrations
(`apps/api/alembic/`); `alembic upgrade head` initializes a fresh database
from scratch. Details: [docs/architecture/database.md](docs/architecture/database.md).

## API

Versioned REST API under `/api/v1` — matches, competitions, teams, and
search. Full interactive docs at `/docs` (Swagger UI) once the API is
running. Details: [docs/architecture/api-architecture.md](docs/architecture/api-architecture.md).

## Testing

- Backend: `cd apps/api && pytest` — 39 tests covering the mock provider in
  isolation, the service layer, all required endpoints, pagination, and
  error/validation handling (404s, empty search).
- Web: `cd apps/web && npx tsc --noEmit && npx eslint .`
- Mobile: `cd apps/mobile && npx tsc --noEmit && npx expo lint`

## Roadmap (Phase 2+)

Deliberately out of scope for Phase 1, but the architecture (provider
abstraction, service layer, versioned API) is designed not to need a rewrite
for these:

- Redis caching + a background ingestion job (replacing today's
  sync-on-read pattern)
- WebSockets / Server-Sent Events for real-time score push instead of
  client polling
- Push notifications (goal alerts, match start/finish)
- Advanced match statistics (possession, shots, xG) and player statistics
- Betting odds, advertisements, subscriptions/payments
- Social features, AI features, chat
- A real automated type-sharing pipeline between the FastAPI schemas and
  the TypeScript clients (e.g. `openapi-typescript`), replacing the
  hand-synced `packages/shared/types.ts`

## Known limitations (Phase 1)

- Dynamic not-found pages on the web app (invalid match/competition/team id)
  render the correct UI but return HTTP 200 instead of 404, per documented
  Next.js App Router streaming behavior (a `noindex` meta tag is injected as
  a mitigation). See the web app's git history for details.
- Kickoff times are displayed in UTC, not the viewer's local timezone.
- The mobile app's web-export target (used only for automated verification
  in this environment, not a real target platform) shows a React hydration
  console warning on the search screen; iOS/Android are unaffected.
- No automated frontend component tests yet (manual + build/lint/typecheck
  verification only) — see Roadmap.
