# LivePitch — Real-Time Football Livescore Platform

A football-only livescore platform inspired by apps like LiveScore, SofaScore
and Flashscore — with its own branding, architecture and implementation.
Phase 1 delivered a working, provider-agnostic MVP. Phase 2 made it
real-time: when a match changes, connected web and mobile clients see it
without refreshing — via a Redis-backed cache/messaging layer, a Celery
background sync pipeline with adaptive polling, change detection, and
WebSocket push. **Phase 3 makes it personal**: accounts, favourite
teams/competitions/matches, and push notifications (mobile + web) driven
by that same real-time event stream — additive on top of Phase 1/2, never
required to use the public livescore experience.

## Features

**Phase 1** — Live, today's, and upcoming matches, plus finished results,
grouped by competition; match details (score, status, kickoff, venue,
half-time score, full event timeline); competition pages (fixtures +
standings); team pages (fixtures + results); global search; loading/empty/
error states everywhere; web (Next.js) and mobile (Expo) clients sharing
one API contract.

**Phase 2** —

- Redis cache-aside reads in front of PostgreSQL for every high-read
  endpoint, with documented, non-arbitrary TTLs
- A Celery worker + scheduler doing background provider synchronization
  with **adaptive polling** (live matches polled far more often than
  scheduled/finished ones — never every match, all the time)
- Change detection: only a *meaningful* change (score, status, minute, a
  new event) triggers a broadcast — not every poll
- Redis Pub/Sub bridging the worker to a WebSocket layer
  (`/ws/matches`, `/ws/matches/{id}`) that pushes updates to web and
  mobile clients in real time
- Client-side reconnection with exponential backoff + a REST resync on
  reconnect, on both web and mobile (with app-lifecycle-aware connection
  handling on mobile)
- Stale-data detection (`data_status`: `FRESH`/`STALE`/`UNAVAILABLE`) on
  every match response
- Graceful degradation on provider or Redis outages — the app keeps
  serving the most recent known data rather than crashing or fabricating
  updates
- Idempotent, deduplicated background sync jobs; structured logging;
  basic metrics (`/metrics`) and a dependency-aware `/health`
- The bundled mock provider's "live" fixtures now progress in real time
  (see `docs/architecture/realtime.md`), so the whole pipeline is
  observable end-to-end without any external API credentials

**Phase 3** —

- Accounts: registration, login, logout, password change/reset, secure
  password storage (bcrypt), JWT access + rotating refresh tokens
  (httpOnly cookies on web, `expo-secure-store` on mobile), Redis-backed
  rate limiting on auth endpoints (`docs/architecture/auth.md`)
- Favourite teams, competitions and matches, with a personalised "Your
  feed" section layered on top of — never replacing — the existing public
  livescore board on both web and mobile
- A notification pipeline that consumes the *same* Phase 2 `RealtimeEvent`
  stream as the WebSocket layer, as a fully decoupled second consumer:
  preference matching (per team/competition/match, per event type, with
  sensible defaults), idempotent delivery (a single
  `INSERT ... ON CONFLICT` dedup claim — immune to provider resends,
  Celery retries, and worker restarts alike), and a provider-agnostic
  push abstraction (`docs/architecture/notifications.md`)
- Mobile push via Expo (`expo-notifications`) and browser push via Web
  Push/VAPID, both tapping through to the right match/team/competition
  screen using the same `{type, id}` deep-link payload
- WebSocket connections now accept an optional auth token at the
  documented Phase 2 extension point, without changing anonymous
  connection behavior at all

**Phase 4** —

- A **match centre** on web and mobile: header with LIVE / HALF TIME / FULL
  TIME / kickoff / POSTPONED / CANCELLED, a chronological timeline
  (added time, substitutions as "off → on", cards, VAR, penalties),
  lineups with formation and substitution minutes, team statistics with
  comparison bars, recent form, head-to-head and the competition table —
  kept live by the *same* Phase 2 WebSocket, with lineup/statistics updates
  as new `LINEUP_UPDATED` / `STATISTICS_UPDATED` events
- Team pages (form, fixtures, results, squad, season statistics), player
  pages, competition pages (standings with seasons/groups/provider
  classifications, fixtures, results, top scorers) and database-backed
  search that now also finds players and matches
- A **provider capability model** (`GET /api/v1/capabilities`): each
  provider declares what it really supplies; unsupported features render an
  honest "not available" state instead of empty boxes, and nothing is
  fabricated (a statistic the provider didn't send is shown as unavailable,
  never as 0)
- Standings re-sync when a match *finishes* (not on every live goal), with
  event-driven cache invalidation; all new sync is idempotent
- Full details: `docs/architecture/match-centre.md`

**Phase 5** — per-favourite notification overrides (Default/On/Off per
event, with a global mute that wins), a season selector with on-demand history,
cross-process Prometheus metrics (API + worker + scheduler in one `/metrics`), a
React Native test harness (`npm test` in `apps/mobile`), and plan-gated paid
provider features (`FOOTBALL_API_FEATURES`). Details: `docs/architecture/phase5.md`

**Discovery (the second "Phase 5")** — football news, one search across everything,
trending and a personalised feed, on PostgreSQL + Redis + the existing Celery worker (no
new infrastructure). *(The repository already used the name "Phase 5" for the work
above, so the code, migration and docs call this one "discovery".)*

- **News**: articles linked to the existing teams, players, competitions and matches
  (never copies), with categories (one per competition, plus generic ones), reusable
  tags, a draft → published → archived workflow, a role-gated editor (`editor`/`admin`
  roles granted with `python -m app.cli set-role`), an allow-list **HTML sanitizer**,
  related articles with explained deterministic scoring, and News tabs on team,
  competition, player and match pages (match news: match → team → competition)
- **Unified search**: teams, players, competitions, matches and articles in one
  grouped, relevance-ranked result (exact > prefix > contains > fuzzy) using `pg_trgm`
  indexes; suggestions, popular searches (only phrases several visitors chose a result
  for), recent searches (server-side for signed-in users, on-device otherwise), length
  limits and per-client rate limiting
- **Trending**: transparent, decayed, windowed scores from views (counted in Redis,
  de-duplicated, aggregated into Postgres by a beat task), chosen search results, live
  matches, follows and news — each entry says which signals applied, and entities with
  no signal are not ranked
- **Personalised feed** (`/feed`): fixed, explained tiers — live followed → followed
  team today → followed competition today → upcoming → results → news → searched →
  trending — with an `explanation` on every item; anonymous visitors keep the full public
  experience
- **SEO and sharing**: per-page metadata, one canonical URL per page, Open Graph/Twitter
  cards, schema.org `NewsArticle`/`SportsTeam`/`SportsOrganization`/`Person`/`SportsEvent`,
  `robots.txt`, `sitemap.xml`, native share sheets, `/article/{slug}` deep links
- **Opt-in article notifications** (all off by default, relevance-gated, 3/day cap,
  idempotent) through the existing push pipeline
- Full details: [discovery.md](docs/architecture/discovery.md)

**Phase 6** — media, editorial workflow, community, analytics, predictions and Premium, on
the same PostgreSQL + Redis + Celery + WebSocket stack (the only additions to Docker Compose are
object storage, Prometheus and Grafana). Delivered in two passes; start at
[docs/architecture/phase6.md](docs/architecture/phase6.md).

*6a — platform and creator tools*

- **Media**: image upload to S3/R2/MinIO (or a local directory), validated by content, re-encoded
  to WebP in four sizes, EXIF stripped, served with immutable caching and no filesystem paths
  ([media.md](docs/architecture/media.md))
- **Editorial workflow**: author → review → editor approval → publish, **scheduled publishing**
  (idempotent beat job), full **revision history** with compare and restore, and a mobile
  editor ([editorial-workflow.md](docs/architecture/editorial-workflow.md))
- **Community**: comments and replies (plain text, rate-limited, spam-guarded, reportable,
  moderated), seven **reactions**, editor-created **polls**, opt-in public **profiles** with badges
  ([community.md](docs/architecture/community.md))
- **Observability**: structured JSON logs with request ids, Prometheus metrics, five provisioned
  Grafana dashboards and starter alerts ([observability.md](docs/architecture/observability.md))

*6b — analytics, predictions, Premium*

- **Advanced analytics**: team attack / possession / defence / discipline, player per-90 and
  match-by-match history, form with streaks, head-to-head windows, and a match comparison — every
  figure is provider-capability aware (missing is `—`, never 0)
  ([analytics.md](docs/architecture/analytics.md))
- **Predictions**: a deterministic Poisson model (`poisson-v1`), stored with model version and data
  timestamp, locked at kickoff, **evaluated** against results (Brier score, calibration) —
  labelled "Model estimate", never advice, and no accuracy is claimed without measured evidence
  ([predictions.md](docs/architecture/predictions.md))
- **Insights**: sourced sentences about form, streaks, head-to-head, live match statistics and
  players, persisted with the data version they came from; personalised "for you" lines about
  followed teams and competitions; community interactions can lift items in the feed
- **Monetisation**: provider-independent subscriptions and entitlements, signed + idempotent
  payment webhooks, cancel/renew/payment-failure handling, an ad-eligibility abstraction. Premium
  is enforced **on the server**; livescores, the match centre, news, search and community stay
  free ([monetisation.md](docs/architecture/monetisation.md))
- **Moderation additions**: profile reports and admin account suspension
- Web and mobile UIs for all of it (an *Analysis* tab on matches, *Analytics* on teams, player
  performance, a Premium page, accessible text alternatives for every chart)

## Architecture

```
Football Data Provider (API-Football, or football-data.org)
        │
        ▼
Celery worker  ◄── Celery beat (scheduler)
        │  sync + change detection + Redis Pub/Sub publish
        ▼
PostgreSQL (durable)         Redis (cache-aside + Pub/Sub)
        │                            │
        └─────────────┬──────────────┘
                       ▼
                FastAPI (/api/v1 cache-aside reads, /ws/* WebSocket push)
                       │
        ┌──────────────┼──────────────┐
        ▼                             ▼
      Web (Next.js)                Mobile (Expo)
```

Full write-ups:
[system-architecture.md](docs/architecture/system-architecture.md) ·
[data-flow.md](docs/architecture/data-flow.md) ·
[database.md](docs/architecture/database.md) ·
[api-architecture.md](docs/architecture/api-architecture.md) ·
[realtime.md](docs/architecture/realtime.md) ·
[caching.md](docs/architecture/caching.md) ·
[auth.md](docs/architecture/auth.md) ·
[notifications.md](docs/architecture/notifications.md) ·
[discovery.md](docs/architecture/discovery.md) ·
[background-workers.md](docs/development/background-workers.md) ·
[websockets.md](docs/development/websockets.md) ·
[docker.md](docs/deployment/docker.md)

## Monorepo structure

```
apps/
  api/      FastAPI backend + Celery worker/scheduler
  web/      Next.js web app
  mobile/   Expo React Native app
packages/
  shared/   Hand-synced TypeScript type reference (see its header comment)
docs/
  architecture/
  development/
  deployment/
docker-compose.yml
.env.example
```

## Technology stack

| Layer      | Stack                                                              |
| ---------- | ------------------------------------------------------------------- |
| Backend    | Python, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic, PostgreSQL, httpx, pytest |
| Real-time  | Redis (cache + Pub/Sub), Celery (worker + beat scheduler), WebSockets (FastAPI/Starlette) |
| Auth       | JWT (PyJWT), bcrypt (passlib), Redis-backed rate limiting            |
| Push       | Expo push service (`expo-notifications`), Web Push/VAPID (`pywebpush`) |
| Web        | Next.js 16 (App Router), TypeScript, React 19, Tailwind CSS v4, Vitest |
| Mobile     | Expo SDK 57, React Native, Expo Router, TypeScript                  |
| Infra      | Docker, Docker Compose                                              |

## Quickest start: Docker Compose (everything)

```bash
cp .env.example .env   # override POSTGRES_PORT/REDIS_PORT if already taken
docker compose up --build
```

Starts `postgres`, `redis`, `minio` (S3-compatible object storage), `redis-exporter`,
`api` (runs migrations, then serves), `worker`, `scheduler`, `web`, `prometheus` and `grafana`.
API: http://localhost:8000 (`/docs`, `/health`, `/metrics`). Web: http://localhost:3000.
Prometheus: http://localhost:9090. Grafana: http://localhost:3001 (`admin`/`admin` — change it).
MinIO console: http://localhost:9001. MinIO no longer publishes its community image on Docker Hub,
so Compose uses the Chainguard build (`cgr.dev/chainguard/minio:latest`); swap in any S3-compatible
store via `S3_*` if you prefer. Full details, including why
`worker`/`scheduler` wait on `api`'s healthcheck specifically:
[docs/deployment/docker.md](docs/deployment/docker.md).

`apps/mobile` isn't containerized (native/Expo tooling doesn't fit a
Compose service well) — run it locally (below), pointed at the Dockerized
API.

## Running each app locally (without Docker)

### 1. Backend (`apps/api`)

Needs a reachable PostgreSQL and Redis (either via `docker compose up
postgres redis`, or your own local installs).

```bash
cd apps/api
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # edit DATABASE_URL/REDIS_URL if not using the defaults
alembic upgrade head
uvicorn app.main:app --reload
```

For real-time updates to actually flow, also run the worker and scheduler
(separate terminals, same venv/`.env`):

```bash
celery -A app.worker.celery_app worker --loglevel=info --concurrency=2
celery -A app.worker.celery_app beat --loglevel=info
```

(On Windows outside Docker, add `--pool=solo` to the worker command if you
hit Celery's known prefork issues there — Docker Compose doesn't need this.)

Run the test suite (needs a reachable Postgres — the same one `DATABASE_URL`
points at; a `_test`-suffixed database is created automatically; Redis is
faked in-process via `fakeredis`, no real Redis needed for tests):

```bash
pytest
```

### 2. Web app (`apps/web`)

```bash
cd apps/web
npm install
cp .env.example .env.local 2>/dev/null || printf "NEXT_PUBLIC_API_URL=http://localhost:8000\nNEXT_PUBLIC_WS_URL=ws://localhost:8000\n" > .env.local
npm run dev
```

Open http://localhost:3000. Other scripts: `npm run build`, `npm start`,
`npm run lint`, `npm run typecheck`, `npm test`.

### 3. Mobile app (`apps/mobile`)

```bash
cd apps/mobile
npm install
cp .env.example .env   # EXPO_PUBLIC_API_URL/EXPO_PUBLIC_WS_URL — use your
                        # machine's LAN IP, not localhost, on a physical device
npx expo start
```

Scan the QR code with Expo Go, or press `i`/`a` for a simulator. Other
scripts: `npx tsc --noEmit`, `npx expo lint`.

## Environment variables

See [.env.example](.env.example) (repo root, used by Docker Compose) and the
per-app `.env.example` files in `apps/api`, `apps/web`, `apps/mobile`. Never
commit a real `.env` file or real credentials.

| Variable                       | Used by        | Purpose                                              |
| -------------------------------- | -------------- | ----------------------------------------------------- |
| `DATABASE_URL`                   | api, worker, scheduler | Postgres connection string (asyncpg driver) |
| `REDIS_URL`                      | api, worker, scheduler | Redis connection string (cache + Pub/Sub) |
| `FOOTBALL_DATA_PROVIDER`         | api, worker, scheduler | `api-football` (default) or `real`          |
| `FOOTBALL_API_BASE_URL` / `FOOTBALL_API_KEY` | api, worker, scheduler | Real provider config (only if `FOOTBALL_DATA_PROVIDER=real`) |
| `CORS_ORIGINS`                   | api            | Comma-separated allow-list — also gates WebSocket origins |
| `LIVE_POLL_INTERVAL_SECONDS` / `UPCOMING_POLL_INTERVAL_SECONDS` / `POST_MATCH_SYNC_INTERVAL_SECONDS` | worker, scheduler | Adaptive polling intervals |
| `REDIS_LIVE_MATCH_TTL_SECONDS` / `REDIS_DEFAULT_TTL_SECONDS` | api | Cache TTLs |
| `WEBSOCKET_HEARTBEAT_SECONDS` / `WEBSOCKET_MAX_CONNECTIONS` | api | WebSocket heartbeat + connection cap |
| `SYNC_MAX_RETRIES` / `SYNC_BACKOFF_SECONDS` | worker | Provider retry/backoff |
| `FOOTBALL_API_LEAGUE_IDS`        | api, worker    | API-Football league ids to expose (default `39,140,135` = Premier League, La Liga, Serie A) |
| `JWT_SECRET` / `JWT_ALGORITHM` | api | Access token signing — **override `JWT_SECRET` outside local dev** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` / `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` | api | Token lifetimes |
| `RATE_LIMIT_REGISTER_PER_HOUR` / `RATE_LIMIT_LOGIN_PER_MINUTE` / `RATE_LIMIT_PASSWORD_RESET_PER_HOUR` | api | Redis-backed auth rate limits |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | api, worker | Web Push — blank skips web push registration (not an error) |
| `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` | web | REST / WebSocket base URLs (server-side) |
| `NEXT_PUBLIC_BROWSER_API_URL` | web | Where the **browser** reaches the API for client-side calls (Docker: `http://localhost:8000`; build-time) |
| `NEXT_PUBLIC_SITE_URL` | web | Canonical public origin for SEO (canonical links, Open Graph, sitemap; build-time) |
| `EXPO_PUBLIC_SITE_URL` | mobile | Public web origin used for share links |
| `TRUSTED_PROXY_CIDRS` | api | Proxies whose `X-Forwarded-For` is believed (per-visitor rate limits); empty = never |
| `ARTICLE_IMAGE_ALLOWED_HOSTS` | api | Hostnames article images may come from (empty = any http/https) |
| `TRENDING_WINDOW_HOURS` / `TRENDING_HALF_LIFE_HOURS` / `CONTENT_NOTIFICATION_DAILY_CAP` / `SEARCH_RATE_LIMIT_PER_MINUTE` / `POPULAR_SEARCH_MIN_VIEWERS` | api | Discovery tuning, documented in `apps/api/.env.example` |
| `EXPO_PUBLIC_API_URL` / `EXPO_PUBLIC_WS_URL` | mobile | REST / WebSocket base URLs |
| `MEDIA_STORAGE_BACKEND` / `S3_ENDPOINT_URL` / `S3_BUCKET` / `S3_REGION` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `MEDIA_PUBLIC_BASE_URL` / `PUBLIC_API_URL` | api, worker | Media storage (`s3` \| `local`) and the URL clients use to reach images |
| `LOG_FORMAT` / `LOG_LEVEL` / `SERVICE_NAME` | api, worker, scheduler | Structured logging |
| `ANALYTICS_CACHE_TTL_SECONDS` / `PREDICTION_CACHE_TTL_SECONDS` / `PREDICTION_HORIZON_HOURS` / `ANALYTICS_PER_MINUTE` | api, worker | Analytics + prediction tuning |
| `BILLING_PROVIDER` / `BILLING_WEBHOOK_SECRET` / `STRIPE_SECRET_KEY` / `BILLING_SUCCESS_URL` / `BILLING_CANCEL_URL` / `BILLING_GRACE_DAYS` | api | Billing. `test` provider is refused when `ENVIRONMENT=production`; set a long random `BILLING_WEBHOOK_SECRET` |
| `ADS_ENABLED` | api | Reserve labelled ad slots (no ad network or tracking is built in) |
| `PROMETHEUS_PORT` / `GRAFANA_PORT` / `GRAFANA_ADMIN_PASSWORD` / `MINIO_PORT` / `MINIO_CONSOLE_PORT` | compose | Monitoring and storage ports |

Full documentation (defaults, TTL strategy, polling rationale) in
`apps/api/.env.example`, `docs/architecture/caching.md`,
`docs/architecture/realtime.md`, `docs/architecture/auth.md`, and
`docs/architecture/notifications.md`.

## Football data provider

The app uses **API-Football** (api-sports.io v3) by default, via
`apps/api/app/services/providers/api_football_provider.py`. Set in `.env`:

```
FOOTBALL_DATA_PROVIDER=api-football
FOOTBALL_API_KEY=<your api-sports key>
FOOTBALL_API_LEAGUE_IDS=39,140,135   # Premier League, La Liga, Serie A
```

There is no bundled mock data: the database is filled from the provider on startup
and by the background sync. The deterministic fake provider used by the test suite
lives in `apps/api/tests/fakes/` and is not importable from the app.

A football-data.org adapter (`FOOTBALL_DATA_PROVIDER=real`, `real_provider.py`) is
also included. Mind your plan's daily request quota when tuning
`LIVE_POLL_INTERVAL_SECONDS`.

## Database

SQLAlchemy 2.x models for `Competition`, `Team`, `Player`, `Match`,
`MatchEvent`, (Phase 2) `Standing`, and (Phase 3) `User`, `RefreshToken`,
`PasswordResetToken`, `FavouriteTeam`/`FavouriteCompetition`/
`FavouriteMatch`, `Device`, `NotificationPreference`, `NotificationLog`,
with indexes on provider IDs, competition/team foreign keys, kickoff time,
match status, and every Phase 3 user-owned relationship. Alembic manages
migrations (`apps/api/alembic/`); `alembic upgrade head` initializes a
fresh database from scratch, including Phase 2 and Phase 3's schema.
Details: [docs/architecture/database.md](docs/architecture/database.md).
Redis is a cache + messaging layer only — never the source of truth,
including for Phase 3's user relationships; see
[docs/architecture/caching.md](docs/architecture/caching.md).

## API

Versioned REST API under `/api/v1` — matches, competitions, teams,
search, plus Phase 3's `auth`, `users`, `favourites`, `devices`, and
`notifications` — and `/ws/matches`/`/ws/matches/{id}` for real-time push
(now accepting an optional auth token; see `docs/architecture/auth.md`).
Full interactive REST docs at `/docs` (Swagger UI) once the API is running.
Details: [docs/architecture/api-architecture.md](docs/architecture/api-architecture.md),
[docs/architecture/realtime.md](docs/architecture/realtime.md),
[docs/architecture/auth.md](docs/architecture/auth.md),
[docs/architecture/notifications.md](docs/architecture/notifications.md).

## Testing

- Backend: `cd apps/api && pytest` — covers the test fake provider (including
  its time-evolving live-match simulation), the service layer's cache-aside
  reads, all REST endpoints, pagination/error/validation handling, the
  Redis service and cache-aside layer, change detection, event
  idempotency/dedup, provider retry/backoff, the WebSocket connection
  manager + endpoints, and (Phase 3) auth, favourites, devices/preferences,
  notification preference-matching/dedup, and notification delivery.
- Web: `cd apps/web && npx tsc --noEmit && npx eslint . && npm test` —
  `npm test` (Vitest) covers the WebSocket client's reconnect/backoff/
  heartbeat behavior and the real-time hooks' pure update logic (applying
  an incoming message, deriving live/today/upcoming/finished views).
- Mobile: `cd apps/mobile && npx tsc --noEmit && npx expo lint && npm test` — `jest-expo` +
  React Native Testing Library (component, hook and screen tests, including the unified
  search screen, news components and deep-link allow-list). The jest suite can time out
  individual tests (5 s) on a heavily loaded machine; they pass when run alone.
- **Phase 6 results (final run):** backend **631** tests (full run: 629 passed, then the 2 that failed were fixed and re-run green;
  Phase 5 baseline was 377), web **140** (baseline 100), mobile **157** (baseline 86); `tsc`, lint and the production web
  build are clean. The backend suite now builds the schema once per session and empties tables between tests
  (about 20 minutes instead of 50+ on a Docker/Windows machine). Benchmarks: `apps/api/scripts/benchmark.py`,
  `apps/api/scripts/ws_fanout.py`.
- Discovery adds `test_html_sanitizer`, `test_news_content`, `test_discovery_search`,
  `test_discovery_engagement`, `test_discovery_feed`, `test_content_notifications`,
  `test_client_ip` and the end-to-end `test_discovery_e2e` to the backend suite (the full
  backend suite takes ~12 minutes: every test rebuilds the schema).

## Roadmap (Phase 4+)

Deliberately out of scope for Phase 3, but the architecture is designed
not to need a rewrite for these:

- Momentum / attack-pressure visualisations and derived advanced metrics
  (need a provider that supplies the underlying data — see
  `docs/architecture/match-centre.md` §9)
- Real transactional email delivery (password reset currently logs the
  link server-side and returns it in dev-only responses — see
  `docs/architecture/auth.md`)
- Betting odds (never planned — predictions are statistical estimates only), chat
- A real automated type-sharing pipeline between the FastAPI schemas and
  the TypeScript clients (e.g. `openapi-typescript`), replacing the
  hand-synced `packages/shared/types.ts`

## Known limitations

- **Discovery**: editing is raw HTML behind a server sanitizer. Trending means *attention*, needs
  real traffic to say much, and lags by 1–5 minutes (counters are aggregated by a beat task,
  at-least-once). The sitemap lists main pages, competitions and articles, not every
  team/player/match. Details: [discovery.md](docs/architecture/discovery.md) §10.

- **Phase 6 predictions** are a simple independent-Poisson model (`poisson-v1`). It ignores
  injuries, lineups, rest and opposition quality beyond goals, has no measured track record yet
  (the evaluation endpoint reports its own sample size and a no-skill baseline), and refuses to
  predict when either team has fewer than 3 stored results. There are no player or team-trajectory
  predictions. Details: [predictions.md](docs/architecture/predictions.md).
- **Phase 6 analytics** depend on what the provider supplied: xG exists only where
  `match_statistics.expected_goals` was populated; expected assists, progressive passes and player
  xG are not stored. The mock provider populates only some statistics.
- **Billing**: the Stripe adapter has not been exercised against a live Stripe account (the signing
  scheme, event mapping and idempotency are tested with synthetic events), plans and prices are
  placeholders, and there are no trials, coupons, tax or invoice screens. The **mobile app sends
  people to the website to subscribe** — selling digital subscriptions in-app normally requires
  Apple/Google billing, which is a product decision not implemented here
  ([monetisation.md](docs/architecture/monetisation.md)).
- **Ads** are an eligibility abstraction with labelled empty slots; no ad network is integrated.
- **Media**: no antivirus or perceptual-hash scanning of uploads; `photo_url` on players is overwritten
  by provider sync; media URLs are resolved when an article is saved; the mobile editor has no
  revision-comparison screen (the API supports it); article view counts lag by the aggregation interval.
- **Not verified**: there is no browser or device automation (no Playwright/Detox), so the
  "login → open match → analytics → prediction → comment → react → vote" journey is covered by API
  integration tests, component tests and a manual Docker run rather than a UI end-to-end test.

- **Phase 4 data availability depends on the provider.** With the bundled
  mock everything is populated (squads are padded with labelled generic
  players; statistics/history are generated). With the real
  football-data.org free tier, match events, lineups and match/player
  statistics are *not available* (declared in `capabilities`), shirt
  numbers and qualification zones aren't supplied, and dates of birth are
  intentionally not stored.
- Head-to-head and form are computed from matches already stored, so they
  are only as deep as the synced history.
- Squads and player profiles are fetched lazily: the first visit to a team
  page may show "squad is still loading" until the worker's on-demand sync
  completes.
- Web/mobile match-centre UIs are verified by typecheck/lint, the shared
  logic's unit tests, a production build and a manual run — not by browser
  or device automation.

- Dynamic not-found pages on the web app (invalid match/competition/team id)
  render the correct UI but return HTTP 200 instead of 404, per documented
  Next.js App Router streaming behavior (a `noindex` meta tag is injected as
  a mitigation). See the web app's git history for details.
- Kickoff times are displayed in UTC, not the viewer's local timezone.
- The mobile app's web-export target (used only for automated verification
  in this environment, not a real target platform) shows a React hydration
  console warning on the search screen; iOS/Android are unaffected.
- Mobile has component/hook tests (Phase 5) but no on-device/E2E automation.
- Metrics are aggregated across processes via Redis and scraped by the bundled Prometheus/Grafana
  (Phase 6); `/metrics` is unauthenticated like `/health` — keep it off the public internet.
- Mobile push notifications require this Expo project to be linked to an
  EAS project (`expo.dev` account, `eas init`) before a real push token
  can be obtained — an external, one-time setup step outside this
  repository's code. `registerForPushNotificationsAsync` degrades
  gracefully (logs a warning, skips registration) without it.
- No real email delivery — password reset links are logged server-side
  and returned directly in the API response in non-production
  environments (see `docs/architecture/auth.md`), matching this repo's
  existing "mock provider" approach to infrastructure this environment
  doesn't have credentials for.
- The paid-plan football-data.org mapping (`FOOTBALL_API_FEATURES`) has only
  been tested against payloads shaped like the documented API, not a live
  paid account (`docs/architecture/phase5.md` §5).
- The mock provider's simulated live-match progression (real time, ~2s per
  simulated minute by default) means kickoff times reported for "live"
  fixtures drift from wall-clock reality the longer a process runs — a
  deliberate trade-off for having *something* to demo in real time without
  a real provider; see `docs/architecture/realtime.md`.

## Production readiness (Phase 7)

Start at [docs/production-launch-checklist.md](docs/production-launch-checklist.md). Architecture, deployment, operations, security, disaster-recovery and runbook documents live under `docs/`; release notes are in `docs/release-notes/v2.1.0.md`.
