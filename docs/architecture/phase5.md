# Phase 5: overrides, season history, metrics, mobile tests, paid-plan features

Five additive pieces on the Phase 1-4 architecture.

## 1. Per-favourite notification overrides

Backend: `DELETE /api/v1/notifications/preferences?scope_type=&scope_id=&event_type=`
removes one explicit override (204, idempotent, only the caller's rows; `scope_id`
is required for team/competition/match and forbidden for global — 422 otherwise).
`PATCH` (unchanged) creates/updates one, so each (favourite, event) is
**Default** (no row), **On** or **Off**.

Semantics are the Phase 3 dispatcher's, unchanged: a user is notified if **any**
scope that covers the match (followed team, competition or the match itself)
allows the event — a scope without an override uses the event's built-in default
(all five notifiable events are on) — and a **global "off"** silences the event
everywhere. The UI says exactly that, and shows "Silenced everywhere by your
global setting" next to a favourite whose event the global toggle mutes. Because
of the "any" rule, muting one of two favourites that both cover a match does not
silence it; the copy tells users to switch the event off for each covering
favourite.

Clients: web `components/notification-settings.tsx` (expandable per favourite, a
`<select>` per event), mobile `app/notification-settings.tsx` +
`components/override-control.tsx` (radio group). Pure logic lives in
`lib/notification-overrides.ts` (identical on web and mobile, unit-tested).

## 2. Season selector and history

- `GET /competitions/{id}/seasons` → `{current, seasons[], historical_supported}`.
- `season` query params are validated (`^\d{4}(/\d{2})?$`, otherwise 422).
- Providers gain `get_historical_standings` / `get_historical_top_scorers` (default:
  unsupported) and the `historical_seasons` capability. Mock: a deterministic past
  table per season. Real football-data.org: `?season=<start year>`; a 400/403/404
  (past seasons are plan-limited) means "none", not a retry storm.
- **On demand, never in the read path**: asking for a season we haven't stored
  answers `[]` and queues `sync_competition_season(competition_id, season)` at most
  once per hour per (competition, season), under the same global budget as other
  on-demand syncs, and only for sane labels (not in the future, at most 10 years
  back). The task upserts idempotently and invalidates that season's cache keys.
- Clients: a season picker on the Standings and Top scorers tabs (web `<select>`,
  mobile chips). Stored seasons first; when the provider supports history, up to 5
  earlier ones ("load"). Choosing an unstored season shows "Loading season…",
  re-checks every 3 s up to 6 times, then says the provider has nothing for it. The
  current season is the server-rendered data, restored instantly when selected.

## 3. Mobile test harness

`apps/mobile`: `npm test` (jest-expo + React Native Testing Library 14, which is
async: `await render(...)`, `await fireEvent.press(...)`). `jest.setup.ts` mocks
`expo-router`'s `Link`. Covered: the match-centre building blocks (header in every
status, timeline sentences, statistics rows with unsupplied values, lineup rows,
standings rows and legend, head-to-head, tab bar, feature states, the
stale-connection banner), `useMatchDetail` (messages, refresh plan, de-duplication,
full-time table re-checks, reconnect, offline), `useSeasonView` (polling, give-up,
stale responses) and the notification settings screen. Writing them found a real
accessibility gap (the stale banner wasn't an accessible element) and a fragile
effect dependency in the season hook; both are fixed.

## 4. Cross-process metrics

Every process (API, worker, scheduler) pushes counters to Redis; `GET /metrics`
renders the combined view, one series per `role` label:

```
cache_hits_total{role="api"} 1204
provider_requests_total{role="worker"} 311
live_matches{role="worker"} 7
```

- Counters: `football:metrics:counters:{role}` hashes, monotonic (they survive
  restarts, so `rate()` keeps working). Buffered in-process and flushed at most once
  per second, so hot paths don't become Redis round trips.
- Gauges: `football:metrics:gauges:{role}:{pid}` with a 90 s TTL (a dead process's
  gauges expire) and summed across the live processes of a role.
- Opt-in per process (`metrics.enable_aggregation`): the API lifespan and Celery's
  `worker_process_init` / `beat_init`; roles come from `METRICS_ROLE` (set per
  service in `docker-compose.yml`). Best-effort: a Redis outage never raises into
  application code, and `/metrics` falls back to the local process's counters.

## 5. Paid-plan provider features (football-data.org)

`FOOTBALL_API_FEATURES=events,lineups,statistics` (comma separated; empty = free
tier). Each flag turns on exactly its capability and the mapping from the v4 match
resource: `goals` / `bookings` / `substitutions` → events (own goals, penalties,
second yellows, added time; a substitution is on/off), `homeTeam.lineup` / `bench`
/ `formation` → lineups (unpublished lineups are skipped, not empty-filled),
`homeTeam.statistics` → team statistics (pass accuracy and xG stay unsupplied).
Per-player match statistics are not in the API and stay unsupported. The match
detail is fetched once per poll for all three features (10 s cache), and with
events on, live matches are fetched in detail — otherwise the list payload would
look like "no events" and clear the stored timeline.

**Verification limit**: there is no paid API key in this repository, so this is
tested against payloads *shaped like* the documented v4 resource
(`tests/test_phase5.py`), not against a live paid account. Check it against your
own key before relying on it.
