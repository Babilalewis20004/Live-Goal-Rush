# Data Flow

## The pipeline (Phase 2)

```
Football Data Provider
        │   (mock: in-memory, time-evolving for live matches — see
        │    architecture/realtime.md | real: httpx calls to an external API)
        ▼
Provider Adapter                    FootballDataProvider methods return
        │                           provider-agnostic DTOs (ProviderMatch,
        │                           ProviderTeam, ProviderCompetition, ...)
        │                           — see apps/api/app/services/providers/schemas.py
        ▼
Celery worker (app/worker/tasks.py) Only the worker calls the provider now
        │                           (plus the startup seed) -- see
        │                           "Background sync" below.
        ▼
Normalization                       FootballService.sync_match() maps
        │                           those DTOs onto internal SQLAlchemy
        │                           models (Competition, Team, Player,
        │                           Match, MatchEvent, Standing), upserting
        │                           by provider_id / (match_id, provider_id)
        │                           (apps/api/app/services/upsert.py)
        ▼
Database (PostgreSQL)                The database is always the source of
        │                           truth -- routers never see raw
        │                           provider payloads, and (as of Phase 2)
        │                           never trigger provider I/O either
        ▼
Cache-aside read (Redis)             FootballService's read methods check
        │                           Redis first, fall back to a Postgres
        │                           read on a miss -- see
        │                           architecture/caching.md
        ▼
FastAPI (/api/v1 + /ws)              Routers/WebSocket handlers call
        │                           FootballService and return its
        │                           Pydantic models / RealtimeEvents
   ┌────┴────┐
   ▼         ▼
 Web       Mobile
```

## Background sync (Phase 2's ingestion strategy)

Phase 1 had no background job — `FootballService` synced provider data
into Postgres **as part of serving a read** ("sync-on-read"). Phase 2
replaces this entirely: reads (`GET /api/v1/matches/live`,
`/matches/{id}`, ...) now only ever touch Redis/Postgres; a Celery worker,
driven by Celery beat on independently configurable intervals, is the only
thing that calls the provider (besides the one-time startup seed below).
See `architecture/realtime.md` for the full pipeline (adaptive polling,
change detection, Pub/Sub, WebSocket push) and
`development/background-workers.md` for the worker/scheduler themselves.

This means a **freshly booted database with no successful sync yet
legitimately has nothing to return** for `/matches/live` — an empty list
(`200`), not an error, and not a synchronous provider call to paper over
it (spec §5/§6 explicitly rule that out). `data_status: "UNAVAILABLE"` on
any match data that does exist without a `last_synced_at` communicates
this to clients rather than silently looking identical to "genuinely no
live matches right now" (see `realtime.md`'s stale-data section).

## Startup seeding

On boot, `apps/api/app/main.py`'s lifespan handler still calls
`FootballService.sync_all_competitions_and_fixtures()`
(`apps/api/app/services/seed.py`), which walks every competition the
provider knows about and syncs its current fixtures, events, **and
standings** (Phase 2 addition — see `database.md`'s `standings` table).
This means `GET /api/v1/teams/{id}` and friends work immediately after
startup, without waiting for the Celery beat schedule's first cycle to
populate the database. If seeding fails (e.g. a real provider is briefly
unreachable at boot), the app still starts — it's logged, not fatal — and
the worker's regular sync jobs will populate the database shortly after.

## Match events

`MatchEvent` rows are synced (`with_events=True`) by every worker task
that touches a match's full detail — which, in Phase 2, is effectively all
of them (a finished match still needs its event timeline populated once
for the detail page to show it, since there's no more sync-on-read
fallback to do it lazily). Unlike Phase 1's delete-and-reinsert, Phase 2
upserts events by a stable `(match_id, provider_id)` identity — see
`database.md`'s "Event identity" note — because change detection needs an
event's database id to stay the same across polls to tell "already knew
about this" apart from "this is new" (`architecture/realtime.md`).

## Web and mobile fetch paths

Both clients call the same `/api/v1/*` endpoints directly over HTTP for
their initial load — no client-side provider coupling, no shared
server-side rendering between them, no GraphQL/BFF layer — and now also
open a WebSocket (`/ws/matches` or `/ws/matches/{id}`) for live updates
after that initial load, per `architecture/realtime.md`. Each REST request
is still an independent HTTP call to FastAPI, served cache-aside; the
WebSocket connection is a separate, long-lived channel layered alongside
it, not a replacement for it.
