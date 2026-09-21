# Data Flow

## The pipeline

```
Football Data Provider
        │   (mock: in-memory, deterministic relative to "now"
        │    real: httpx calls to an external API)
        ▼
Provider Adapter                    FootballDataProvider methods return
        │                           provider-agnostic DTOs (ProviderMatch,
        │                           ProviderTeam, ProviderCompetition, ...)
        │                           — see apps/api/app/services/providers/schemas.py
        ▼
Normalization                       FootballService._sync_* methods map
        │                           those DTOs onto internal SQLAlchemy
        │                           models (Competition, Team, Player,
        │                           Match, MatchEvent), upserting by
        │                           provider_id (apps/api/app/services/upsert.py)
        ▼
Service Layer                       FootballService also reads back from
        │                           the database (with eager-loaded
        │                           relationships) and maps rows onto
        │                           Pydantic response schemas
        ▼
Database (PostgreSQL)                The database is always the source of
        │                           truth for reads — routers never see
        │                           raw provider payloads
        ▼
FastAPI (/api/v1)                    Routers call FootballService and
        │                           return its Pydantic models directly
   ┌────┴────┐
   ▼         ▼
 Web       Mobile
```

## Sync-on-read (Phase 1's ingestion strategy)

Phase 1 has no background job or scheduler. Instead, `FootballService`
syncs provider data into Postgres **as part of serving a read**:

- `GET /api/v1/matches/live` calls `provider.get_live_matches()`, upserts
  every returned match (and its competition/teams) into the database, then
  reads those rows back out (with relationships loaded) to build the
  response.
- `GET /api/v1/matches/{id}` reads the match by internal id from the
  database first (to recover its `provider_id`), then re-fetches that one
  match from the provider to refresh its score/events, syncs, and re-reads.
- Detail endpoints (`/competitions/{id}`, `/teams/{id}`, ...) depend on the
  entity already existing in the database — see "Startup seeding" below for
  why that's reliable even before any traffic arrives.

This keeps the architecture simple for Phase 1 while still exercising a
real, relational, indexed Postgres schema (not a passthrough cache). The
trade-off — every list request does provider I/O — is exactly what the
Phase 2 caching layer (Redis, described in the roadmap) is designed to sit
in front of, without routers or the sync logic needing to change.

## Startup seeding

On boot, `apps/api/app/main.py`'s lifespan handler calls
`FootballService.sync_all_competitions_and_fixtures()`
(`apps/api/app/services/seed.py`), which walks every competition the
provider knows about and syncs its current fixtures (including events).
This means `GET /api/v1/teams/{id}` and friends work immediately after
startup, without requiring a prior list request to have "discovered" that
team first. If seeding fails (e.g. a real provider is briefly unreachable
at boot), the app still starts — it's logged, not fatal — and list
endpoints will populate the database on first successful request.

## Match events

`MatchEvent` rows are only synced when a match's *detail* is fetched
(`with_events=True` in `FootballService._sync_match`) — list endpoints
(`/matches/live`, `/matches/today`, ...) return `MatchSummary` without an
event timeline, since fetching and normalizing events for every match in a
list is unnecessary I/O for a summary view. Each detail sync replaces that
match's events wholesale (delete + re-insert) rather than trying to
reconcile a diff, since Phase 1's mock data is fully deterministic per call
and a real provider's event list for a finished match doesn't change.

## Web and mobile fetch paths

Both clients call the same `/api/v1/*` endpoints directly over HTTP — there
is no client-side provider coupling, no shared server-side rendering
between them, and no GraphQL/BFF layer. Each request from a client is an
independent HTTP call to FastAPI, which performs the sync-on-read flow
above transparently.
