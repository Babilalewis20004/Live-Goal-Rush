# Real-Time Architecture (Phase 2)

## The goal

> When a football match changes, connected users should receive the
> update without manually refreshing the application.

Phase 1 had no mechanism for this — every client request was a
synchronous "call the provider, sync it, read it back" round trip
(`docs/architecture/data-flow.md`'s "sync-on-read" section, now
historical). Phase 2 replaces that with a background pipeline that polls
the provider on its own schedule, detects what actually changed, and pushes
it to connected clients over WebSockets — while REST/cache-aside reads
(`caching.md`) keep working for the initial load and for clients that
aren't (yet, or ever) connected over a WebSocket.

## Pipeline

```
Football Provider (mock: now time-evolving — see below | real: unchanged)
       │
       ▼
Celery worker  ◄── Celery beat (scheduler; see development/background-workers.md)
       │  1. sync_match() -- upsert provider data into Postgres (idempotent)
       │  2. change_detection.detect_changes() -- diff against the last
       │     published state (stored in Redis, no TTL)
       │  3. publish each resulting RealtimeEvent to Redis Pub/Sub,
       │     and invalidate the cache entries it affects
       ▼
PostgreSQL (durable)         Redis (Pub/Sub channel: football:events)
                                     │
                                     ▼
                              WebSocket pub/sub bridge (one per API
                              process, app/websocket/pubsub_bridge.py)
                                     │
                                     ▼
                              ConnectionManager (app/websocket/manager.py)
                                     │
                        ┌────────────┼────────────┐
                        ▼                          ▼
                 /ws/matches                /ws/matches/{id}
                 (every connected client)   (only that match's subscribers)
                        │                          │
                        ▼                          ▼
                      Web                        Mobile
```

The worker never imports anything from `app/websocket/` and never knows
whether any client is connected — it only publishes to a Redis channel.
The WebSocket layer never imports anything from `app/worker/` — it only
subscribes to that channel. Redis Pub/Sub is the entire coupling between
them (spec §13).

## Change detection

`app/services/change_detection.py::detect_changes(match, previous)`
compares a freshly-synced `MatchDetail` against the last snapshot
published for that match (`build_state_snapshot`, stored at
`football:match:{id}:state`, no TTL — overwritten every sync) and returns
zero or more `RealtimeEvent`s. **A poll that finds nothing different from
the last poll publishes nothing** — this is what keeps a 15-second poll
interval from becoming a 15-second broadcast-everything-regardless-of-content
interval.

What counts as a change:

| Diff | Event(s) |
| --- | --- |
| Status transition | `MATCH_STARTED` / `SECOND_HALF_STARTED` (scheduled→live vs. halftime→live), `HALF_TIME`, `MATCH_FINISHED`, `MATCH_POSTPONED`, `MATCH_CANCELLED` |
| A new event id appears in `match.events` (a goal/card/sub/etc. was added) | `GOAL`, `CARD`, `SUBSTITUTION`, or `MATCH_UPDATED` for anything else, based on `event_type` |
| Score or minute changed, but no status transition and no new event | `MATCH_UPDATED` |
| Nothing changed | nothing published |

Relies on match event ids being **stable across polls** — see
`database.md`'s "Event identity" note; without the Phase 2 upsert-by-identity
change to event syncing, every poll would look like "all-new events" and
every poll would broadcast a flood of false `GOAL`/`CARD` events.

## Event model

```json
{
  "type": "MATCH_UPDATED",
  "match_id": "123",
  "timestamp": "2026-09-21T20:15:00Z",
  "data": {
    "home_score": 2,
    "away_score": 1,
    "status": "LIVE",
    "minute": 67
  }
}
```

`app/events/schemas.py::RealtimeEvent`. Types: `MATCH_STARTED`,
`MATCH_UPDATED`, `GOAL`, `CARD`, `SUBSTITUTION`, `HALF_TIME`,
`SECOND_HALF_STARTED`, `MATCH_FINISHED`, `MATCH_POSTPONED`,
`MATCH_CANCELLED` (`RealtimeEventType`). Adding a new type is additive —
extend the enum, extend `change_detection.py`'s mapping — no existing
consumer needs to change to keep working (unrecognized types are just
values clients don't specially handle yet).

## Adaptive polling

Not every match is polled at the same frequency (spec §9) — the worker
runs three sync jobs on independently configurable intervals
(`app/worker/schedule.py`, all from `Settings`, none hard-coded):

| Job | Interval (env var) | Selects matches by |
| --- | --- | --- |
| `sync_live_matches` | `LIVE_POLL_INTERVAL_SECONDS` (15s) | Asks the provider for exactly what it considers live right now (`get_live_matches()`) — not a database scan, since the provider already scopes this |
| `sync_upcoming_kickoffs` | `UPCOMING_POLL_INTERVAL_SECONDS` (60s) | **Database-driven** (spec §8): `SCHEDULED` matches within 15 minutes of kickoff either way — these are the ones most likely to have just gone live |
| `sync_post_match` | `POST_MATCH_SYNC_INTERVAL_SECONDS` (60s) | **Database-driven**: `FINISHED` matches synced within the last 30 minutes — catches a late provider correction, then polling for that match stops on its own once it ages out of the window |

`sync_fixtures` (today/tomorrow/7-day window/yesterday) and
`sync_competitions` (metadata/fixtures/standings) run on coarser fixed
intervals — see `development/background-workers.md`. Full lifecycle:

```
scheduled
   │  (sync_upcoming_kickoffs checks it every 60s once kickoff is <15m away)
   ▼
LIVE ──► HALFTIME ──► LIVE ──► FINISHED
   (sync_live_matches checks every 15s the whole time it's LIVE/HALFTIME)
                                  │
                                  ▼
                    (sync_post_match checks it every 60s for 30 more
                     minutes, then stops)
```

## Provider rate-limit protection

Every provider call the worker makes goes through
`app/worker/provider_guard.py::call_with_backoff`, which:

- Counts requests/errors/429s (`provider_requests_total`,
  `provider_errors_total`, `provider_rate_limited_total` — see
  `app/services/metrics.py`)
- Retries up to `SYNC_MAX_RETRIES` (default 3) times
- Backs off exponentially between attempts — `SYNC_BACKOFF_SECONDS *
  2^attempt` (default: 5s, then 10s) — explicitly not retrying a 429
  immediately
- Raises `ProviderUnavailableError` after exhausting retries, which every
  sync task catches, logs, and treats as "skip this cycle" rather than
  crashing the worker process or corrupting partial state

`RealFootballDataProvider`'s free-tier limitations (football-data.org):
10 requests/minute, narrower competition/match coverage than the mock
dataset, and no event timeline or unified search endpoint — see the
docstring in `app/services/providers/real_provider.py`. The adaptive
polling intervals above default to values well under that budget for a
handful of tracked competitions, but should be raised
(`LIVE_POLL_INTERVAL_SECONDS` in particular) if you activate a real
provider with a tighter limit or track more competitions.

## Mock provider: simulated live progression

The bundled `MockFootballDataProvider` (Phase 1) was a pure function of
wall-clock time — a "live" fixture's minute and score were frozen at
whatever `mock_data.py` hard-coded, forever. That made Phase 2's real-time
pipeline have nothing to actually observe: change detection would never
find a difference between polls. `app/services/providers/mock_provider.py`
now makes "live"/"halftime" fixtures progress deterministically from the
API process's start time, cycling through
`live (0-45') → halftime → live (45-90') → finished → (repeats)`, at a
configurable rate (`MOCK_LIVE_SECONDS_PER_MINUTE`, default: 2 real seconds
per simulated match-minute). Events reveal progressively as the simulated
clock passes each one's minute, and the score is derived by counting
revealed goal-type events rather than trusted from a static field — so
simply running the stack and waiting produces real, provider-agnostic
score/event changes for the worker to detect and broadcast. This is mock-only
behavior; `RealFootballDataProvider` is untouched and doesn't need it —
real matches change on their own.

## WebSocket endpoints

- **`/ws/matches`** — general feed; every connected client receives every
  match's updates. Used by the home/livescore board.
- **`/ws/matches/{match_id}`** — scoped to one match; only that match's
  subscribers receive its updates (spec §16). Used by the match detail
  page. `match_id` is format-validated (must be a plain integer) before a
  connection is even accepted — a client cannot subscribe to an arbitrary
  string as if it were a resource (spec §29).

Message shape (`app/api/v1/websocket.py` + `app/websocket/pubsub_bridge.py`):

```json
{
  "type": "MATCH_UPDATED",
  "match": { "id": "123", "home_score": 2, "away_score": 1, "status": "live", "minute": 67 }
}
```

A `GOAL`/`CARD`/`SUBSTITUTION` message additionally carries `match.event`
(the single new event: id, type, minute, team_id, player name,
description) — see `RealtimeMatchPayload`/`RealtimeMatchEvent` in
`packages/shared/types.ts`.

### Connection management (spec §15)

`app/websocket/manager.py::ConnectionManager` owns all connection state —
`general_connections` (a set) and `match_connections` (match id → set) —
so this logic doesn't leak into `FootballService` or route handlers.
Responsibilities: connect/disconnect, broadcast (general and per-match),
and dead-connection cleanup (a failed `send_json` during a broadcast
removes that connection instead of taking the whole broadcast down).

### Security (spec §29)

- **Origin validation**: a WebSocket's `Origin` header, if present, must
  be in `CORS_ORIGINS` — the same allow-list CORS already uses. Absent
  (non-browser clients, including the mobile app) is allowed.
- **Connection cap**: `WEBSOCKET_MAX_CONNECTIONS` (default 1000) per API
  process; over the cap, new connections are rejected with a policy-violation
  close code before being accepted.
- **Message validation**: inbound frames over 2KB or that aren't valid
  JSON are dropped (logged, not fatal to the connection).
- **No arbitrary resource subscriptions**: see the `match_id` format
  validation above.
- **Auth-ready, not authenticated**: Phase 1 never added user accounts, so
  there's nothing to authenticate against yet. `_origin_allowed`'s call
  site in `app/api/v1/websocket.py` is where a token check would go.
- Provider credentials (`FOOTBALL_API_KEY`) never appear in any WebSocket
  payload, log line, or error response — they exist only in
  `RealFootballDataProvider`'s constructor and outbound request headers.

### Heartbeat / dead-connection detection

Each connection's receive loop (`app/api/v1/websocket.py::_receive_loop`)
answers a client-sent `{"type":"PING"}` with `{"type":"PONG"}`, and treats
`2 * WEBSOCKET_HEARTBEAT_SECONDS` of silence from the client as a dead
connection — closing it with a normal-closure code rather than leaving the
transport to drop it abruptly. Both web and mobile clients
(`lib/realtime.ts`) send a ping every `WEBSOCKET_HEARTBEAT_SECONDS`.

## Client reconnection (spec §18/§19/§20)

`apps/web/lib/realtime.ts` and `apps/mobile/src/lib/realtime.ts` are
parallel implementations (browser `WebSocket` vs. React Native's) of the
same `RealtimeConnection` contract:

- Exponential backoff with jitter on an unexpected close, capped at 30s —
  never a tight reconnect loop.
- **Before** opening the next socket, an `onReconnect` callback re-fetches
  the relevant REST endpoint, so a client that missed messages while
  disconnected resyncs its state rather than silently drifting (spec §18).
- One reusable hook per concern
  (`apps/web/hooks/use-livescore-board.ts` /
  `apps/web/hooks/use-match-detail.ts`, and their mobile equivalents in
  `apps/mobile/src/hooks/`) rather than every page reimplementing its own
  WebSocket wiring (spec §20) — `REST state (seed) + WebSocket updates =
  current application state`.
- **Mobile only**: `AppState` handling (spec §19) closes the socket when
  the app backgrounds and reconnects (after a REST refresh) on foreground,
  so a backgrounded app doesn't hold an idle connection open indefinitely.

## Stale-data detection (spec §21)

`Match.last_synced_at` (set on every provider sync) backs a computed
`data_status` field (`FRESH` / `STALE` / `UNAVAILABLE`) on every
`MatchSummary`/`MatchDetail` response
(`apps/api/app/schemas/match.py::MatchSummary.data_status`), computed at
*serialization* time against "now" — not baked in when the row was synced
or when a cache entry was written — so a match sitting in Redis for most
of its TTL still reports accurate freshness. Threshold: 3x the relevant
poll interval for live matches, 2x the default cache TTL otherwise; no
sync ever having succeeded reports `UNAVAILABLE`. Clients can use this to
show "updated Ns ago" / a stale-data indicator instead of silently
presenting old data as current (spec §21's explicit requirement).

## Provider failure handling (spec §22)

If the provider becomes unreachable: `call_with_backoff` exhausts its
retries, the affected sync task logs it and returns without touching the
database, and the API keeps serving whatever was last successfully synced
— `data_status` on that data degrades to `STALE` (and eventually
`UNAVAILABLE` if the outage is long enough that no sync ever ran) rather
than the API crashing or the database being wiped. `GET /health` reports
the provider sub-status independently (see `development/websockets.md`
and `deployment/docker.md` for the full health-check picture) so an
operator can tell "the provider is down but everything else is fine" apart
from "the whole stack is down."
