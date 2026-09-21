# System Architecture

## Overview

LivePitch Phase 1 is a monorepo with one backend and two clients sharing a
single API contract:

```
apps/
  api/      FastAPI backend — the only thing that talks to a football
            data provider, and the only thing that talks to PostgreSQL.
  web/      Next.js web app — talks only to apps/api.
  mobile/   Expo React Native app — talks only to apps/api.
packages/
  shared/   Reference TypeScript types (hand-synced with apps/api's
            Pydantic schemas; see its header comment for why).
```

Neither client ever talks to a football data provider or a database
directly. This is what makes "swap the mock provider for a real one" a
one-file change (`apps/api/app/services/providers/__init__.py`) rather than
a cross-cutting rewrite.

## Backend layering

```
Router (apps/api/app/api/v1/*.py)
   │  — HTTP concerns only: path/query params, status codes, pagination
   ▼
Service (apps/api/app/services/football_service.py)
   │  — business logic: sync provider data into the DB, build responses
   ▼
Provider (apps/api/app/services/providers/*)     Database (SQLAlchemy)
   │  — external football data                      │  — persisted, normalized
   ▼                                                 ▼
Mock or Real API                                PostgreSQL
```

Routers never construct SQL or call a provider directly — they depend on
`FootballService` via FastAPI's dependency injection
(`apps/api/app/api/deps.py`). This is also where a caching layer (Redis,
per the Phase 2 roadmap) would slot in later, without routers or clients
needing to change: `FootballService` is the one place that would gain a
cache-aside check before hitting the provider/DB.

## Provider abstraction

`FootballDataProvider` (`apps/api/app/services/providers/base.py`) is an
abstract base class with nine methods (`get_live_matches`, `get_fixtures`,
`get_match`, `get_competitions`, `get_competition_fixtures`,
`get_standings`, `get_team`, `get_team_fixtures`, `search`). Two concrete
implementations exist behind it:

- `MockFootballDataProvider` — deterministic, in-memory, no network calls.
  Used by default (`FOOTBALL_DATA_PROVIDER=mock`).
- `RealFootballDataProvider` — an `httpx`-based adapter targeting
  football-data.org's v4 API as a concrete example. Inactive by default
  (requires `FOOTBALL_DATA_PROVIDER=real` plus real credentials — see the
  root README's "Activating a real football data provider" section).

`app/services/providers/__init__.py::get_provider()` is the single factory
function that decides which one to construct, based on `Settings`. Nothing
else in the codebase imports a concrete provider class directly.

## Web and mobile

Both clients are intentionally thin:

- Web (`apps/web`): Next.js App Router, Server Components fetch directly
  from the API (`apps/web/lib/api.ts`), every data-fetching page is
  `export const dynamic = "force-dynamic"` so live scores are never
  static-generated or cached across builds.
- Mobile (`apps/mobile`): Expo Router, client-side `useEffect` + `fetch`
  against the same API (`apps/mobile/src/lib/api.ts`).

Both keep a hand-synced copy of the API's response types
(`apps/web/types/api.ts`, `apps/mobile/src/types/api.ts`), documented as
mirrors of `packages/shared/types.ts` and, ultimately, of
`apps/api/app/schemas/*.py`. See that file's header comment for why there is
no automated type-sharing pipeline yet (a Phase 2 candidate).

## Why these technology choices

- **FastAPI + Pydantic**: async-native, automatic OpenAPI docs, and
  Pydantic schemas give free request/response validation — matches the
  spec's requirement for consistent error responses and documented
  endpoints with minimal boilerplate.
- **SQLAlchemy 2.x (async) + Alembic**: typed ORM models with a real
  migration history, so "initialize a fresh database from scratch" is
  `alembic upgrade head`, not a hand-run SQL script.
- **PostgreSQL**: required by the spec; also a sensible real-world choice
  for relational match/competition/team data with foreign keys.
- **Next.js App Router**: Server Components let the web app fetch data
  without shipping a client-side data-fetching library, and file-based
  routing maps cleanly onto match/competition/team detail pages.
- **Expo + Expo Router**: file-based routing consistent with the web app's
  mental model, and a single codebase that targets iOS, Android, and (for
  this environment's automated verification only) web.
- **Docker Compose, no Redis**: per the Phase 1 spec, a caching layer is
  designed for (see the service layer above) but not built yet — adding
  Redis now would be complexity without a corresponding requirement.
