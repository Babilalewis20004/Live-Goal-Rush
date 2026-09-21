# API Architecture

Base path: `/api/v1`. Interactive docs (Swagger UI) at `/docs`, raw OpenAPI
schema at `/openapi.json`, once the API is running. Health check at
`/health`, metrics at `/metrics`, WebSocket endpoints at `/ws/*` — all
unversioned, outside `/api/v1` (see `deployment/docker.md` and
`development/websockets.md` for those).

## Endpoints

### Matches

| Method & path                         | Description                                      |
| --------------------------------------- | ------------------------------------------------- |
| `GET /api/v1/matches/live`              | Matches currently `live` or `halftime`            |
| `GET /api/v1/matches/today`             | All of today's fixtures, any status               |
| `GET /api/v1/matches/upcoming`          | Scheduled matches with a future kickoff (looks up to 7 days ahead) |
| `GET /api/v1/matches/{match_id}`        | Full match detail, including the event timeline   |
| `GET /api/v1/matches/{match_id}/events` | Just the event timeline for a match               |

### Competitions

| Method & path                                        | Description                          |
| ------------------------------------------------------ | -------------------------------------- |
| `GET /api/v1/competitions`                              | Paginated list of all competitions    |
| `GET /api/v1/competitions/{competition_id}`             | Single competition                    |
| `GET /api/v1/competitions/{competition_id}/fixtures`    | Paginated fixtures for that competition |
| `GET /api/v1/competitions/{competition_id}/standings`   | Ranked standings table                |

### Teams

| Method & path                              | Description                              |
| --------------------------------------------- | ------------------------------------------ |
| `GET /api/v1/teams/{team_id}`                 | Single team                                |
| `GET /api/v1/teams/{team_id}/fixtures`        | Paginated upcoming (`scheduled`) fixtures  |
| `GET /api/v1/teams/{team_id}/results`         | Paginated `finished` results               |

### Search

| Method & path                | Description                                       |
| ------------------------------ | --------------------------------------------------- |
| `GET /api/v1/search?q=...`     | Teams, competitions and players matching the query. Empty/missing `q` returns empty lists (200), not an error. |

## Response shapes

Every response is built from Pydantic schemas in `apps/api/app/schemas/` —
never a raw provider payload. Nested objects (a match's `competition`,
`home_team`, `away_team`) are always fully embedded, not just an id, so
clients don't need a second round-trip to render a match card.

```jsonc
// GET /api/v1/matches/{id}
{
  "id": 1,
  "competition": { "id": 1, "name": "Champions League", "country": "Europe", "logo_url": null, "type": "international" },
  "home_team": { "id": 1, "name": "Real Madrid", "short_name": "RMA", "country": "Spain", "logo_url": null },
  "away_team": { "id": 2, "name": "Manchester City", "short_name": "MCI", "country": "England", "logo_url": null },
  "kickoff_time": "2026-09-21T12:14:07Z",
  "status": "live",
  "home_score": 2,
  "away_score": 2,
  "half_time_home_score": null,
  "half_time_away_score": null,
  "minute": 74,
  "venue": "Santiago Bernabéu",
  "last_synced_at": "2026-09-21T21:28:14Z",  // Phase 2
  "data_status": "FRESH",                     // Phase 2 -- FRESH | STALE | UNAVAILABLE
  "events": [
    { "id": 41, "event_type": "goal", "minute": 12, "extra_minute": null,
      "team": { "...": "TeamOut" }, "player": { "...": "PlayerOut" },
      "assist_player": { "...": "PlayerOut" }, "description": null }
  ]
}
```

`last_synced_at`/`data_status` appear on every `MatchSummary`/`MatchDetail`
(so list endpoints carry them too, not just detail) — computed at response
time from `Match.last_synced_at`, not stored as `data_status` itself. See
`architecture/realtime.md`'s "Stale-data detection" section.

## Real-time (Phase 2)

REST remains the way every client gets its *initial* state. For updates
after that without polling, see `/ws/matches` and `/ws/matches/{match_id}`
— full contract in `architecture/realtime.md` and
`development/websockets.md`.

## Pagination

List endpoints that can return more than a handful of rows
(`/competitions`, `/competitions/{id}/fixtures`, `/teams/{id}/fixtures`,
`/teams/{id}/results`) accept `page` (default 1, min 1) and `page_size`
(default 20 or 50 depending on endpoint, min 1, max 100) query parameters
and return:

```jsonc
{ "items": [ /* ... */ ], "total": 6, "page": 1, "page_size": 20 }
```

`/matches/live`, `/matches/today`, `/matches/upcoming`, and `/search` are
not paginated — their result sets are inherently small (a day's worth of
matches, or a handful of search matches), so pagination would add
complexity without benefit.

## Error handling

- **Unknown id** (match/competition/team) → `404` with
  `{"detail": "<Entity> not found"}`.
- **Invalid query params** (e.g. `page_size=1000`) → `422` from FastAPI's
  built-in Pydantic validation, with the standard FastAPI validation-error
  body.
- **Anything unexpected** (provider unreachable, a bug) → `500` with
  `{"detail": "Internal server error"}` — the actual exception is logged
  server-side (`apps/api/app/main.py`'s global exception handler) but never
  returned to the client, so stack traces and internal details never leak.
- **Empty search** → `200` with empty lists, not an error — an empty result
  is a valid, expected state, not a failure.

## Versioning

Everything lives under `/api/v1`. A breaking change to a response shape
would ship as `/api/v2` alongside it rather than mutating `/api/v1` in
place, so existing web/mobile client builds don't break out from under
them.
