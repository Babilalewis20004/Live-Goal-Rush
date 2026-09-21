# Database

PostgreSQL, managed with SQLAlchemy 2.x (async, `apps/api/app/models/`) and
Alembic (`apps/api/alembic/`). `alembic upgrade head` builds the full schema
from nothing — there is no manual SQL setup step.

## Tables

### `competitions`

| Column        | Type               | Notes                                  |
| ------------- | ------------------ | --------------------------------------- |
| `id`          | integer PK         |                                          |
| `provider_id` | varchar(64)        | unique, indexed — maps to the provider's own id |
| `name`        | varchar(255)       | indexed                                 |
| `country`     | varchar(100)       | nullable                                |
| `logo_url`    | varchar(512)       | nullable                                |
| `type`        | enum (string)       | `league` \| `cup` \| `international`   |
| `created_at`, `updated_at` | timestamptz | |

### `teams`

| Column        | Type          | Notes                     |
| ------------- | ------------- | -------------------------- |
| `id`          | integer PK    |                             |
| `provider_id` | varchar(64)   | unique, indexed             |
| `name`        | varchar(255)  | indexed                     |
| `short_name`  | varchar(50)   | nullable                    |
| `country`     | varchar(100)  | nullable                    |
| `logo_url`    | varchar(512)  | nullable                    |
| `created_at`, `updated_at` | timestamptz | |

### `players`

| Column        | Type          | Notes                                  |
| ------------- | ------------- | ---------------------------------------- |
| `id`          | integer PK    |                                           |
| `provider_id` | varchar(64)   | unique, indexed                          |
| `name`        | varchar(255)  | indexed                                  |
| `position`    | varchar(50)   | nullable                                 |
| `photo_url`   | varchar(512)  | nullable                                 |
| `team_id`     | integer FK → `teams.id`, nullable, indexed | `ON DELETE SET NULL` |
| `created_at`, `updated_at` | timestamptz | |

### `matches`

| Column                  | Type          | Notes                                    |
| ------------------------ | ------------- | ------------------------------------------ |
| `id`                     | integer PK    |                                             |
| `provider_id`            | varchar(64)   | unique, indexed                            |
| `competition_id`         | integer FK → `competitions.id`, indexed | `ON DELETE CASCADE` |
| `home_team_id`, `away_team_id` | integer FK → `teams.id`, indexed | separate FKs, no self-referential ambiguity |
| `kickoff_time`           | timestamptz   | indexed                                    |
| `status`                 | enum (string) | `scheduled`\|`live`\|`halftime`\|`finished`\|`postponed`\|`cancelled`, indexed |
| `home_score`, `away_score` | integer     | default 0                                  |
| `half_time_home_score`, `half_time_away_score` | integer, nullable | |
| `venue`                  | varchar(255)  | nullable                                   |
| `minute`                 | integer, nullable | current live minute — an addition beyond the spec's minimum field list, needed to render an in-progress match without the client recomputing elapsed time |
| `last_synced_at`         | timestamptz, nullable | **(Phase 2)** set by every provider sync (worker task or startup seed); drives `data_status` (FRESH/STALE/UNAVAILABLE) in API responses — see [realtime.md](realtime.md#stale-data-detection) |
| `created_at`, `updated_at` | timestamptz | |

Composite indexes: `(competition_id, kickoff_time)` and
`(status, kickoff_time)` — these back the `/matches/live`,
`/matches/today`, `/matches/upcoming`, and `/competitions/{id}/fixtures`
query patterns.

### `match_events`

| Column               | Type          | Notes                                   |
| --------------------- | ------------- | ------------------------------------------ |
| `id`                  | integer PK    |                                             |
| `provider_id`         | varchar(64), nullable | indexed; nullable because not every mock event has a natural provider id |
| `match_id`            | integer FK → `matches.id`, indexed | `ON DELETE CASCADE` |
| `event_type`          | enum (string) | `goal`\|`own_goal`\|`penalty`\|`penalty_missed`\|`yellow_card`\|`red_card`\|`substitution`\|`var` |
| `minute`, `extra_minute` | integer, `extra_minute` nullable | |
| `team_id`             | integer FK → `teams.id`, nullable, indexed | |
| `player_id`, `assist_player_id` | integer FK → `players.id`, nullable, `player_id` indexed | |
| `description`         | varchar(512), nullable | free text (e.g. "Penalty") |
| `created_at`, `updated_at` | timestamptz | |

**(Phase 2)** unique constraint `uq_match_events_match_provider` on
`(match_id, provider_id)` — see "Event identity" below.

### `standings` (Phase 2)

| Column               | Type          | Notes                                   |
| --------------------- | ------------- | ------------------------------------------ |
| `id`                  | integer PK    |                                             |
| `competition_id`      | integer FK → `competitions.id`, indexed | `ON DELETE CASCADE` |
| `team_id`             | integer FK → `teams.id`, indexed | `ON DELETE CASCADE` |
| `position`, `played`, `won`, `drawn`, `lost`, `goals_for`, `goals_against`, `points` | integer | |
| `created_at`, `updated_at` | timestamptz | |

Unique constraint `uq_standings_competition_team` on `(competition_id,
team_id)`. Added in Phase 2 so `GET /competitions/{id}/standings` can be
served cache-aside from the database like every other read (Phase 1 fetched
standings live from the provider on every request, since nothing persisted
them) — the worker's competition sync job keeps this table current.

## Relationships

```
Competition 1──* Match
Competition 1──* Standing
Team        1──* Match        (as home_team, separately as away_team)
Team        1──* Player
Team        1──* Standing
Match       1──* MatchEvent   (cascade delete)
Team        1──* MatchEvent   (optional)
Player      1──* MatchEvent   (optional, both as player and as assist_player)
```

## Design notes

- **Enums stored as strings** (`native_enum=False`) rather than native
  Postgres `ENUM` types, so adding a new status/event type is a code change
  plus a migration that doesn't need `ALTER TYPE ... ADD VALUE` (which has
  its own transactional quirks in Postgres).
- **`provider_id` is the join key back to the external world.** Every table
  except `match_events` enforces uniqueness on it, which is what makes the
  service layer's upsert-by-provider-id pattern
  (`apps/api/app/services/upsert.py`) safe to call repeatedly without
  creating duplicates.
- **Event identity (Phase 2).** `match_events.provider_id` is no longer
  purely optional metadata: every sync assigns it a value -- the
  provider's own event id when available (the mock provider always
  supplies one), otherwise a deterministic hash of the event's
  match/type/minute/team/player (`football_service._synthetic_event_key`)
  -- and the table enforces uniqueness on `(match_id, provider_id)`.
  Combined with `upsert_by_unique_fields`
  (`apps/api/app/services/upsert.py`), re-syncing a match upserts its
  events in place instead of Phase 1's delete-all-then-reinsert. This
  matters beyond simple dedup: an event's database id now stays stable
  across polls, which is what lets change detection
  (`apps/api/app/services/change_detection.py`) tell "this event already
  existed" apart from "this is new" by diffing id sets.
- **Timestamps** (`created_at`, `updated_at`) are on every table via a
  shared `TimestampMixin`, server-defaulted so they're set correctly even
  for rows inserted outside the ORM.

## Migrations

```bash
cd apps/api
alembic revision --autogenerate -m "describe the change"   # generate
alembic upgrade head                                        # apply
alembic downgrade -1                                         # roll back one
```

Two migrations exist: the initial schema
(`f95a7852dc3f_initial_schema.py`, all five Phase 1 tables) and Phase 2's
`ad4916a7b31a_phase_2_realtime_infrastructure.py` (`matches.last_synced_at`,
the `standings` table, the `match_events` identity constraint). `env.py` is
configured for SQLAlchemy's async engine (via `asyncpg`), so autogeneration
and upgrades both run against the real async models — there's no separate
sync-only shadow configuration to keep in sync.
