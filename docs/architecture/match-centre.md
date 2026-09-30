# Match Centre & Football Data (Phase 4)

Phase 4 turns the livescore app into a football *information* platform: a
match centre (timeline, lineups, statistics, form, head-to-head, table),
team pages, player pages, competition pages with standings and top
scorers, and database-backed search. Everything is **additive** on the
Phase 1–3 architecture — same provider abstraction, same Celery workers,
same Redis cache-aside, same change-detection → Pub/Sub → WebSocket
pipeline. There is no second real-time pipeline.

```
FootballDataProvider ──► Provider* DTOs (normalized) ──► services ──► PostgreSQL
   (mock | real)                                            │
                                                            ├─► Redis cache-aside ──► REST (/api/v1/...)
                                                            └─► change detection ──► Pub/Sub ──► WebSocket
```

## 1. Provider capabilities

Nothing in Phase 4 assumes a provider can supply everything. Each provider
declares what it supports (`FootballDataProvider.capabilities`,
`app/services/providers/schemas.py::ProviderCapabilities`). The sync layer
checks the flag *before* calling an optional method, and the API exposes
it at **`GET /api/v1/capabilities`** so clients can tell "this provider
never supplies lineups" (*Not available*) from "lineups haven't been
published yet" (*check back later*).

| Feature | Mock provider | `RealFootballDataProvider` (football-data.org free tier) |
| --- | --- | --- |
| Match events | YES | **NO** (free tier has no event timeline) |
| Lineups | YES (live/finished matches) | **NO** |
| Match statistics | YES (live/finished) | **NO** |
| Player match statistics | YES | **NO** |
| Team statistics | derived from standings (see §6) | derived from standings |
| Standings (season, groups, form) | YES | YES |
| Top scorers | YES | YES (`/competitions/{id}/scorers`) |
| Team squads | YES | YES (`/teams/{id}` → `squad`) |
| Player profiles | YES | YES (`/persons/{id}`) — no shirt number; date of birth deliberately not stored |
| Venue | YES | YES |
| Head-to-head | derived from stored results | derived from stored results |
| Form | derived from stored results | derived from stored results |
| Expected goals | omitted by the mock on purpose (demonstrates "not supplied") | n/a |

Head-to-head and form are **never** provider capabilities: they are
computed from finished matches already in our database, so they work with
any provider (and are simply short/empty when little history is stored).

The optional interface methods (`get_lineups`, `get_match_statistics`,
`get_player_statistics`, `get_team_squad`, `get_player`, `get_top_scorers`)
are **not abstract** — they default to "unsupported" (empty/`None`), so a
provider implements only what it can genuinely supply. The real provider's
mapping from football-data.org's raw JSON to the normalized DTOs is covered
by tests using recorded-shape payloads (`tests/test_match_centre_sync.py`).

### Normalization

Every provider returns the same `Provider*` DTOs (`ProviderLineup`,
`ProviderTeamMatchStatistics`, `ProviderTopScorer`, `ProviderPlayer`,
`ProviderStandingRow`…). Raw provider field names, positions ("Centre-Back",
"Offence" → `Defender`/`Forward`), season labels and form strings
("W,D,L" → `WDL`) are translated *inside* the provider implementation; the
database models, API schemas, web and mobile never see them.

## 2. Data model (migration `b30168d59097`)

New tables: `match_lineups` + `lineup_players`, `match_statistics`,
`player_match_statistics`, `player_season_statistics`. Extended:
`match_events.event_detail`, `players.{nationality, shirt_number,
profile_synced_at}`, `teams.venue`, `standings.{season, group_name,
description, form}`. Existing entities were reused, not duplicated.

- **`NULL` means "the provider did not supply this"**, never 0. Every
  statistic column is nullable; the API and both clients omit a statistic
  that is null for both teams and show "–" when only one side lacks it.
- **Identity / idempotency**: unique constraints on `(match_id, team_id)`
  (lineups, team statistics), `(lineup_id, player_id)`,
  `(match_id, player_id)`, `(player_id, competition_id, season)` and
  `(competition_id, season, group_name, team_id)` (standings). Repeated
  syncs update in place and never duplicate.
- **Seasons** are a short label (`2026/27`) stored next to whatever they
  scope — there is no Season table. Providers state their own; the
  fallback is the European convention (`app/services/season.py`).
  `group_name` is `""` (not NULL) for a single table, so the standings
  unique constraint actually deduplicates.
- **Search indexes**: `pg_trgm` GIN indexes on `teams.name`,
  `players.name`, `competitions.name` (the migration creates the
  extension); composite `(team_id, kickoff_time)` indexes on `matches`
  for form / head-to-head / team fixtures.
- **Migration safety**: only additive changes plus a swap of the standings
  unique constraint. `standings.season` is added with a temporary default,
  back-filled with the current season label, then the default is dropped.
  Verified on a fresh database and on a populated Phase 3 database;
  downgrade/re-upgrade round-trips.

Event conventions: a `substitution` event has `player` = who came **on**
and `assist_player` = who went **off**. Timeline ordering is
`(minute, extra_minute or 0, id)` so `45'` < `45+2'` < `46'`.

## 3. API

All under `/api/v1`, public (football data stays public; user endpoints
keep their Phase 3 authorization). Unknown ids → 404; a known match whose
provider lacks the data → **200 with an explicit empty payload**.

| Endpoint | Notes |
| --- | --- |
| `GET /capabilities` | What the active provider supplies |
| `GET /matches/{id}` · `/events` | Existing; events gain `event_detail` |
| `GET /matches/{id}/lineups` | `{home, away}` each `{team, formation, starters, substitutes}`; `subbed_in_minute`/`subbed_out_minute` derived from the timeline; both `null` = not supplied |
| `GET /matches/{id}/statistics` | `{home, away}` team stats, nullable fields |
| `GET /matches/{id}/players` | Per-player match statistics, home side first |
| `GET /matches/{id}/form?scope=overall\|venue` | Both teams' last 5 results *before this match* |
| `GET /matches/{id}/head-to-head` | Last ≤5 finished meetings within a stated window (`period_start`..`before`, 10 years), wins relative to this match's home/away team |
| `GET /teams/{id}` | `TeamDetail`: + `venue`, `competitions` |
| `GET /teams/{id}/players` | Squad, sorted GK→FWD then shirt number |
| `GET /teams/{id}/statistics` | One row per competition+season(+group), from the official table |
| `GET /teams/{id}/form?scope=overall\|home\|away` | Last 5 results, most recent first, plus `sequence` (oldest→newest) |
| `GET /teams/{id}/fixtures` · `/results` | Existing; `/results` is now newest-first |
| `GET /players/{id}` · `/statistics` | Profile; season totals per competition + last 10 appearances |
| `GET /competitions/{id}/fixtures?scope=all\|upcoming\|results` | `all` keeps the Phase 1 behaviour; `results` is newest-first |
| `GET /competitions/{id}/standings?season=&group=` | Latest stored season by default; rows carry `season`, `group_name`, `description`, `form`, `goal_difference` |
| `GET /competitions/{id}/top-scorers?season=` | Ranked, always tagged with competition + season |
| `GET /search?q=` | Teams, competitions, players **and matches** |

Existing endpoints were extended rather than duplicated (the spec's
`/teams/{id}/matches` is the existing `/fixtures` + `/results`;
`/competitions/{id}/matches` is `/fixtures?scope=`).

**Form and head-to-head are historical only.** They are labelled as such in
the UI and nothing in the system uses them to predict anything.

**Search** queries the database first (trigram-indexed `ILIKE`, every query
`LIMIT`ed, `%`/`_` escaped so user input can't act as wildcards) and only
falls back to the provider when nothing stored matches. Matches shown are
those involving a matched team, nearest to "now" first.

## 4. Synchronization

| Task | Trigger | Does |
| --- | --- | --- |
| `_sync_one_match` (inside `sync_live_matches` / `sync_upcoming_kickoffs` / `sync_post_match`) | existing beats | Existing score/event sync **plus** `MatchCentreService.sync_match_extras`: lineups, team statistics, player statistics — capability-gated, through `GuardedProvider` (Phase 2 retry/backoff). Failure of the extras never blocks the score sync. |
| `sync_competitions` | existing beat | Also syncs top scorers |
| `sync_competition_standings(competition_id)` | **queued when a match becomes `FINISHED`** | Standings + top scorers for that one competition |
| `sync_team(provider_id)` | on demand | Now also syncs the squad |
| `sync_player(provider_id)` | on demand | Player profile |

Policies that keep this cheap and correct:

- **Live goals don't touch official standings.** Standings are based on
  completed matches: only the `MATCH_FINISHED` transition queues a
  standings sync (the periodic `sync_competitions` remains the backstop).
  Tested end to end.
- **Extras sync only writes what changed**: the match's existing rows are
  loaded in one query and only differing attributes are assigned;
  `FootballService` memoizes identical team/competition/player upserts
  within a run. A starting XI doesn't change once a match is under way
  (substitutions arrive as events), so live/finished matches re-sync
  lineups only if none are stored.
- **An empty provider answer never deletes stored data** (lineups, squads,
  statistics): a transient empty response can't wipe a real squad.
- **Read endpoints never call the provider** (Phase 2 rule). When a read
  finds something the provider could supply but we haven't stored (an
  empty squad, an unenriched player), it queues `sync_team`/`sync_player`
  **once per hour per entity** (`football:sync-requested:*` debounce) and
  returns what it has. The web/mobile squad tab says the squad is still
  loading.
- Unknown provider event types are skipped with a warning instead of
  failing the whole match sync.
- Thin payloads never erase richer data: a match's embedded team (no
  venue) or a bare event player (name only) updates the row without nulling
  fields a squad/profile sync filled in.

## 5. Real-time

Two new `RealtimeEventType`s on the **existing** channel and message
contract (`{type, match: {id, ...data}}`), so no client breaks:

| Type | Fired when | Payload (`match`) |
| --- | --- | --- |
| `LINEUP_UPDATED` | The stored lineups' fingerprint (formations, players, starter flags, shirt numbers) changed | base fields; clients re-fetch `/lineups` |
| `STATISTICS_UPDATED` | Stored team statistics differ from the last published snapshot | base fields + `statistics` (`{home, away}`) |

Both are diffed against the snapshot stored at `football:match:{id}:state`
(extended with `lineup_fingerprint` / `statistics`), so an unchanged poll
publishes nothing, a provider without the data never fires them, and a cold
start announces nothing extra. They are **never push-notified** (not in
`DEFAULT_ON_EVENT_TYPES`; the worker doesn't even enqueue them for
dispatch). `GOAL`/`CARD`/`SUBSTITUTION` payloads now also carry
`extra_minute`, `assist` (for a substitution: the player going off) and
`event_detail`, so a live timeline entry renders fully without a refetch.

Client behaviour (web `hooks/use-match-detail.ts`, mobile
`src/hooks/use-match-detail.ts`; one socket per match centre):

- score/status/minute/events are applied directly; `STATISTICS_UPDATED`
  replaces the statistics; `refreshPlanFor(message)` (pure, unit-tested)
  says what to re-fetch: lineups on `LINEUP_UPDATED`/`SUBSTITUTION`;
  lineups + standings (+ statistics) on `MATCH_FINISHED`, with the
  standings re-check delayed (6 s, 25 s) because the worker syncs them
  *after* full time;
- duplicate in-flight requests are coalesced;
- on reconnect the existing Phase 2 `RealtimeConnection` calls the hook's
  `refresh()` (REST re-fetch) *before* reopening the socket;
- while disconnected a live match shows **"Connection lost — showing the
  last known match state. Updated N seconds ago"** instead of presenting
  stale numbers as live; mobile also re-fetches on returning to the
  foreground and supports pull-to-refresh.

## 6. Standings, teams, players

- **Standings**: persisted per `(competition, season, group, team)`;
  classifications (`description`, e.g. "Champions League", "Relegation")
  and `form` are whatever the provider supplied — the app never hard-codes
  competition rules. The UI only *colours* the provider's text
  (`zoneTone`). Group-stage tables render one table per `group_name`.
- **Team statistics** are taken from the official table rows
  (played/won/drawn/lost/GF/GA/points/position/form) per competition and
  season. Clean sheets and other derived figures are intentionally *not*
  shown: the provider doesn't supply them and we hold only part of a
  season's matches, so computing them would be misleading.
- **Players**: name, position, nationality, shirt number, team, photo URL.
  No date of birth or other personal data is stored. Season totals come
  from top-scorer data; "recent matches" come from stored per-match player
  statistics. A player who only exists as a match-event stub shows what we
  know and triggers a one-off profile sync.
- **Mock provider caveat**: squads are padded with clearly labelled
  generic players ("ARS Player 12") and the mock's history/statistics are
  generated deterministically (`providers/mock_extras.py`) purely so every
  screen has data in development. They are not real football data.

## 7. Caching

See `caching.md` for the key table and TTL rationale. New in Phase 4:
match lineups/statistics/player statistics (TTL by status: live 30 s,
scheduled 300 s, finished 1 h), match form and head-to-head (1 h — they only
look at results before the match), team/player/squad (1 h), team form,
team statistics, top scorers and standings (300 s). Invalidation is
event-driven: new lineup/substitution/statistics data drops the match's
keys, and `MATCH_FINISHED` drops standings, top scorers, both teams'
form/statistics/fixtures.

## 8. Clients

**Web** — `app/match/[id]` (server-fetched first paint, then the live hook):
header (LIVE / HALF TIME / FULL TIME / kickoff + Today/Tomorrow /
POSTPONED / CANCELLED, from the normalized status), tabs *Overview (form,
head-to-head) · Timeline · Stats · Lineups · Table*; `app/team/[id]` tabs
*Overview · Fixtures · Results · Squad · Statistics*; `app/competition/[id]`
tabs *Standings · Fixtures · Results · Top scorers · Teams*;
`app/player/[id]`; search also lists players (linked) and matches. Aliases
`/matches/:id`, `/teams/:id`, `/competitions/:id`, `/players/:id` redirect
to the singular routes (`next.config.mjs`).

**Mobile** — same information architecture on the existing Expo Router
stack (`match/[id]`, `team/[id]`, `competition/[id]`, new `player/[id]`,
deep link scheme `mobile://match/{id}` etc.); every tab body is a
`FlatList` with windowing, pull-to-refresh on the match centre.

Shared pure logic (`lib/match-centre.ts`, identical copies on web and
mobile, enforced by a test): status display, timeline formatting,
statistics rows, refresh plan, live announcements.

**Accessibility**: WAI-ARIA tabs with roving focus and arrow keys (web),
`tab`/`selected` roles (mobile), tables with captions/`scope`/`abbr`,
labelled W/D/L chips and statistic bars, per-event screen-reader text, and
an `aria-live` region that announces only goals and status changes — never
the ticking minute.

## 9. Not included (by design)

No momentum/attack-pressure visualisation and no derived/advanced metrics:
neither provider supplies suitable data, and the spec says not to invent
it. Possession and shot comparisons are shown as bars only for values the
provider actually sent.
