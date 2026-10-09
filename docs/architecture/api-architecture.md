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
| `GET /api/v1/matches/{match_id}/events` | Just the event timeline for a match (ordered `minute`, `extra_minute`, `id`) |
| `GET /api/v1/matches/{match_id}/lineups`     | *(Phase 4)* Both teams' lineups: formation, starting XI, substitutes (with subbed in/out minutes) |
| `GET /api/v1/matches/{match_id}/statistics`  | *(Phase 4)* Team statistics; a `null` field = not supplied by the provider |
| `GET /api/v1/matches/{match_id}/players`     | *(Phase 4)* Per-player match statistics            |
| `GET /api/v1/matches/{match_id}/form`        | *(Phase 4)* Both teams' last 5 results before this match (`scope=overall\|venue`) |
| `GET /api/v1/matches/{match_id}/head-to-head` | *(Phase 4)* Last ≤5 finished meetings inside an explicit window |

### Competitions

| Method & path                                        | Description                          |
| ------------------------------------------------------ | -------------------------------------- |
| `GET /api/v1/competitions`                              | Paginated list of all competitions    |
| `GET /api/v1/competitions/{competition_id}`             | Single competition                    |
| `GET /api/v1/competitions/{competition_id}/fixtures`    | Paginated matches; `?scope=all` (default) \| `upcoming` \| `results` (newest first) |
| `GET /api/v1/competitions/{competition_id}/standings`   | Ranked table; *(Phase 4)* `?season=&group=`, rows carry season/group/description/form/goal difference |
| `GET /api/v1/competitions/{competition_id}/top-scorers` | *(Phase 4)* Ranked scorers for a competition + season (`?season=`) |

### Teams

| Method & path                              | Description                              |
| --------------------------------------------- | ------------------------------------------ |
| `GET /api/v1/teams/{team_id}`                 | Single team (*Phase 4:* + `venue`, `competitions`) |
| `GET /api/v1/teams/{team_id}/fixtures`        | Paginated upcoming (`scheduled`) fixtures  |
| `GET /api/v1/teams/{team_id}/results`         | Paginated `finished` results (newest first) |
| `GET /api/v1/teams/{team_id}/players`         | *(Phase 4)* Squad                          |
| `GET /api/v1/teams/{team_id}/statistics`      | *(Phase 4)* Per competition+season table figures |
| `GET /api/v1/teams/{team_id}/form`            | *(Phase 4)* Last 5 results (`scope=overall\|home\|away`) |

`GET /api/v1/competitions/{id}/seasons` *(Phase 5)* lists stored seasons for the
season selector; `DELETE /api/v1/notifications/preferences` *(Phase 5)* resets one
per-favourite override. See `phase5.md`.

### Players *(Phase 4)*

| Method & path                                   | Description                                   |
| ------------------------------------------------- | ----------------------------------------------- |
| `GET /api/v1/players/{player_id}`                 | Profile (name, position, nationality, shirt number, team) |
| `GET /api/v1/players/{player_id}/statistics`      | Season totals per competition + last 10 appearances |

### Capabilities *(Phase 4)*

| Method & path                | Description                                       |
| ------------------------------ | --------------------------------------------------- |
| `GET /api/v1/capabilities`     | What the active data provider supplies (lineups, statistics, squads, ...) so clients can show an honest "not available" state |

### Search

| Method & path                | Description                                       |
| ------------------------------ | --------------------------------------------------- |
| `GET /api/v1/search?q=...&limit=` | Teams, competitions, players, matches and (discovery) **articles**, each group ranked exact > prefix > contains > fuzzy and capped (default 10, max 20). `q` ≤ 100 chars (422 above), rate limited 60/min per client. Empty/missing `q` returns empty lists (200). |
| `GET /api/v1/search/suggestions?q=` | Up to 8 typed suggestions (team/competition/player/article), ≥ 2 characters, cached 2 min |
| `GET /api/v1/search/popular` | Phrases several different visitors chose a result for |
| `GET/DELETE /api/v1/search/recent` | The signed-in caller's own recent searches (`?query=` removes one) |
| `POST /api/v1/search/track` | A search was submitted / a result chosen (204): adds to the caller's recent searches if signed in; choosing a result also feeds trending and popular |

The Phase 4 contract is in `match-centre.md`; the discovery contract in `discovery.md`.

### News and discovery *(discovery brief)*

Full write-up: [discovery.md](discovery.md).

| Method & path | Description |
| --- | --- |
| `GET /api/v1/articles` | Published articles, newest first. Filters: `category`, `tag`, `featured`, `team_id`, `player_id`, `competition_id`, `match_id`. `Page{items,total,page,page_size}` |
| `GET /api/v1/articles/{slug}` | One published article (sanitized `content`, `content_text`, `content_blocks`, linked teams/players/competitions/matches). 404 for drafts/archived |
| `GET /api/v1/articles/{slug}/related?limit=` | Deterministically scored related articles, each with a `reason` |
| `GET /api/v1/articles/categories`, `/tags` | Categories (data, not code); popular tags |
| `GET /api/v1/{teams,players,competitions,matches}/{id}/news` | Articles linked to the entity (a match's news is match → team → competition, labelled by `relation`) |
| `GET /api/v1/discovery/home` | Public home payload: results, featured/latest/trending news, trending teams/players, popular competitions |
| `GET /api/v1/discovery/trending[/{teams\|players\|competitions\|articles}]?window_hours=&limit=` | Trending with explainable `signals` |
| `GET /api/v1/feed` | **Auth.** The caller's personalised, tiered, explained feed |
| `POST /api/v1/engagement/view` | Count one view (204; de-duplicated; rate limited) |
| `GET/PUT /api/v1/notifications/content-preferences` | **Auth.** The five article-notification switches (all off by default) |
| `GET/POST/PATCH/DELETE /api/v1/editor/articles…` | **Editor/admin.** List (own; admin: all), create, edit, `publish`, `unpublish`, `archive`, delete; `POST …/categories` (admin) |

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

## Phase 6 additions

Authentication: ✱ = signed in, ◆ = editor/admin, ★ = admin. "tiered" = the response is trimmed to the caller's
plan by the server; an over-limit request gets `402 {message, entitlement}`.

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /teams/{id}/analytics?scope&window` | tiered | window ∈ 5, 10, 20, 38; >10 needs `extended_history`; 240/min/IP |
| `GET /teams/{id}/form/extended?limit=5or10` | `extended_history` for 10 | form with streaks (`summary`) |
| `GET /players/{id}/analytics?window` | tiered | per-90, history, trend |
| `GET /matches/{id}/comparison` | tiered | cached per tier |
| `GET /matches/{id}/prediction` | tiered | reads the stored estimate; never computes |
| `GET /matches/{id}/head-to-head/extended?window=last5, last10 or all` | `extended_history` unless last5 | |
| `GET /matches/{id}/insight-records`, `/teams/{id}/insight-records`, `/players/{id}/insights` | — | persisted insights with `source_data_version` |
| `GET /predictions/evaluation` | — | accuracy, Brier vs baseline, calibration, sample size |
| `GET /me/insights` | ✱ | sentences about the caller's favourites |
| `GET /me/entitlements` | optional | informational; the server re-checks every request |
| `GET /subscription/plans`, `GET /subscription`, `POST /subscription/checkout`, `POST /subscription/cancel` | none / ✱ | checkout 10/h |
| `POST /billing/webhook` | HMAC signature | idempotent on event id; 120/min/IP |
| `GET /ads/placements?live` | optional | eligibility only |
| `POST /profiles/{id}/report` | ✱ | public profiles only; 10/h |
| `GET /moderation/profile-reports`, `POST /moderation/profile-reports/{id}/resolve` or `/dismiss` | ◆ | |
| `POST /moderation/users/{id}/suspend` or `/unsuspend` | ★ | |

Phase 6a endpoints (media, editorial workflow, comments, reactions, polls, profiles) are documented in
[community.md](community.md), [media.md](media.md) and [editorial-workflow.md](editorial-workflow.md).

Changed, backward-compatibly: `TeamFormOut.summary`; `HeadToHeadOut` gained `window`, `total_meetings`, goals,
`average_goals`, `recent_form`, `complete`, `limitation` and `limit` may be `null`; `FeedItem.reason` gained
`community_match` / `community_article`; reactions have seven kinds; `RealtimeEventType` gained five values.
