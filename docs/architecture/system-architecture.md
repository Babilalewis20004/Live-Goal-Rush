# System Architecture

## Overview

LivePitch is a monorepo with one backend and two clients sharing a single
API contract, plus (as of Phase 2) a Redis-backed cache/messaging layer and
a background sync pipeline:

```
apps/
  api/      FastAPI backend + Celery worker/scheduler — the only thing
            that talks to a football data provider, and the only thing
            that talks to PostgreSQL/Redis.
  web/      Next.js web app — talks to apps/api over REST and WebSocket.
  mobile/   Expo React Native app — talks to apps/api over REST and WebSocket.
packages/
  shared/   Reference TypeScript types (hand-synced with apps/api's
            Pydantic schemas; see its header comment for why).
```

Neither client ever talks to a football data provider, PostgreSQL, or
Redis directly. This is what makes "swap the mock provider for a real
one" a one-file change (`apps/api/app/services/providers/__init__.py`)
rather than a cross-cutting rewrite.

## Backend layering

```
Router (apps/api/app/api/v1/*.py)
   │  — HTTP/WebSocket concerns only: path/query params, status codes,
   │    pagination, connection lifecycle
   ▼
Service (apps/api/app/services/football_service.py)
   │  — business logic: reads are cache-aside (Redis → Postgres, never
   │    the provider — see caching.md); syncs (provider → Postgres) are
   │    now only called by the worker/startup seed, not request handlers
   ▼
Provider (apps/api/app/services/providers/*)     Database (SQLAlchemy)     Cache/messaging (Redis)
   │  — external football data, called only          │  — persisted,          │  — cache-aside +
   │    by the worker (app/worker/tasks.py)           │    normalized          │    Pub/Sub (caching.md,
   ▼                                                   ▼                       │    realtime.md)
Mock or Real API                                  PostgreSQL              Redis
```

Routers never construct SQL, call a provider directly, or touch Redis
directly — they depend on `FootballService`/`CacheAside`/`RedisService` via
FastAPI's dependency injection (`apps/api/app/api/deps.py`). Real-time
push (WebSockets, the Celery worker/scheduler) is a separate, parallel
concern layered alongside this request/response stack — see
`realtime.md` for the full pipeline (provider → worker → change detection
→ Redis Pub/Sub → WebSocket → client) and `caching.md` for the cache-aside
read path.

## Provider abstraction

`FootballDataProvider` (`apps/api/app/services/providers/base.py`) is an
abstract base class with nine methods (`get_live_matches`, `get_fixtures`,
`get_match`, `get_competitions`, `get_competition_fixtures`,
`get_standings`, `get_team`, `get_team_fixtures`, `search`). Two concrete
implementations exist behind it:

- `ApiFootballProvider` — API-Football (api-sports.io v3), the default.
  Selected with `FOOTBALL_DATA_PROVIDER=api-football`; limited to `FOOTBALL_API_LEAGUE_IDS`.
- `RealFootballDataProvider` — an `httpx`-based adapter targeting
  football-data.org's v4 API as a concrete example. Inactive by default
  (requires `FOOTBALL_DATA_PROVIDER=real` plus real credentials — see the
  root README's "Football data provider" section).

`app/services/providers/__init__.py::get_provider()` is the single factory
function that decides which one to construct, based on `Settings`. Nothing
else in the codebase imports a concrete provider class directly.

## Web and mobile

Both clients are intentionally thin, and both now layer a WebSocket
connection on top of their existing REST fetch rather than replacing it
(spec §17/§19 — "the initial HTTP request remains important"):

- Web (`apps/web`): Next.js App Router, Server Components fetch directly
  from the API (`apps/web/lib/api.ts`) for the initial page load; a client
  component then takes over with a reusable real-time hook
  (`apps/web/hooks/use-livescore-board.ts`,
  `apps/web/hooks/use-match-detail.ts`) that opens `apps/web/lib/realtime.ts`'s
  WebSocket client. Every data-fetching page is still
  `export const dynamic = "force-dynamic"` so the initial REST state is
  never static-generated or cached across builds.
- Mobile (`apps/mobile`): Expo Router, client-side `useEffect` + `fetch`
  against the same API (`apps/mobile/src/lib/api.ts`) for the initial
  load, then the same real-time-hook pattern
  (`apps/mobile/src/hooks/`) plus `AppState`-driven connection lifecycle
  (spec §19 — see `realtime.md`).

Both keep a hand-synced copy of the API's response types
(`apps/web/types/api.ts`, `apps/mobile/src/types/api.ts`), documented as
mirrors of `packages/shared/types.ts` and, ultimately, of
`apps/api/app/schemas/*.py` — now including the WebSocket message contract
(`RealtimeMessage`/`RealtimeEventType`), not just REST response shapes. See
that file's header comment for why there is no automated type-sharing
pipeline yet (a Phase 3 candidate).

## Why these technology choices

- **FastAPI + Pydantic**: async-native, automatic OpenAPI docs, and
  Pydantic schemas give free request/response validation — matches the
  spec's requirement for consistent error responses and documented
  endpoints with minimal boilerplate. FastAPI's native WebSocket support
  (Starlette) meant Phase 2's real-time layer didn't need a separate
  framework.
- **SQLAlchemy 2.x (async) + Alembic**: typed ORM models with a real
  migration history, so "initialize a fresh database from scratch" is
  `alembic upgrade head`, not a hand-run SQL script.
- **PostgreSQL**: required by the spec; also a sensible real-world choice
  for relational match/competition/team data with foreign keys. Remains
  the sole durable source of truth in Phase 2 — see `caching.md`.
- **Redis + Celery (Phase 2)**: Redis for both cache-aside reads and
  Pub/Sub messaging (one dependency serving two roles, rather than two
  separate pieces of infrastructure), Celery + Redis-as-broker for
  background sync since nothing in Phase 1 already provided a background
  job system to prefer instead — see `development/background-workers.md`.
- **Next.js App Router**: Server Components let the web app fetch data
  without shipping a client-side data-fetching library, and file-based
  routing maps cleanly onto match/competition/team detail pages.
- **Expo + Expo Router**: file-based routing consistent with the web app's
  mental model, and a single codebase that targets iOS, Android, and (for
  this environment's automated verification only) web.
- **Docker Compose, no Kubernetes/Kafka/RabbitMQ**: FastAPI + PostgreSQL +
  Redis + Celery worker/scheduler + WebSockets is sufficient for this
  stage's real-time requirements (spec §34) — the architecture stays
  modular enough to introduce heavier infrastructure later if scale
  requires it, without a rewrite.
