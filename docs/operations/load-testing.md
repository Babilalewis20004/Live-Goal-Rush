# Load testing

**Everything below was measured on one developer machine** (Windows 10, Docker Desktop/WSL2 with **4 vCPU / 8 GB**), with the load generator, PostgreSQL, Redis, Celery, Prometheus, Grafana, MinIO and
the web container all sharing those 4 vCPUs. Production hardware will differ — in both directions (a Linux VM is faster per core; real networks add latency). Treat the numbers as
**relative evidence** (what saturates first, how much a change helps, how workers scale), not as a capacity promise. Rerun `load/run-suite.sh` against staging before launch.

## Method

* **Tool:** Grafana k6 (v2.3.0) run in Docker on the compose network (`load/k6/scenarios.js`, `load/run-k6.sh`, `load/run-suite.sh`). Earlier attempts with a Python generator saturated the generator before the server, and
  an attempt that sampled `docker stats` every 2 s distorted the system under test; resource use is now read from the containers' cgroup counters before/after each run (zero overhead).
* **Data:** the 304 MB test database (`apps/api/scripts/seed_volume.py`): 20,000 users, 3,000 articles, 440,269 comments, 609,076 notification-ledger rows, 80,000 sessions, 50,002 payment events,
  60,000 favourites (40 % on three teams), on top of 1,140 real matches / 67 teams / 1,672 players. 500 users hold access tokens for the authenticated scenarios.
* **Football provider:** unreachable on purpose (so the test neither spends the real quota nor is helped by it) — which also demonstrates reads do not depend on it.
* **Warm-up:** each scenario is run for 12 s first, then measured for 30 s (+ ramp) so the caches reflect steady state, not a cold start. Cold-start behaviour is in "cold cache" below.
* **Think time** is modelled (1–4 s between actions), so "virtual users" are people, not a closed loop hammering one URL; the "capacity probes" are closed loops with no think time.
* **429s** from the per-IP rate limits are expected under synthetic single-address load and are not counted as errors (search requests send distinct `X-Forwarded-For` values from the trusted Docker network, as nginx would). Errors below are 5xx and transport failures only.

## Scenarios

| # | Scenario | What a virtual user does |
|---|---|---|
| 1 | **home** | opens the home page: the 4 API calls the Next.js page makes, in parallel, then waits 1–3 s |
| 2 | **live** | follows live matches: live list + one match page variant (detail, events, statistics, lineups, form, head-to-head, insights), then 1–4 s |
| 3 | **websocket** | opens `/ws/matches` or a match socket and holds it for 30 s, PING every 5 s |
| 4 | **search** | types search prefixes of team names / football words (`/search`, `/search/suggestions`), 0.5–1.5 s apart |
| 5 | **spike** | match-day surge: ramps 0 → 400 VUs in 30 s on a mix of live list, today, match pages, events, discovery, team, article and comment reads |
| 6 | **community** | during a big match: reads comment threads (40 %), posts comments (25 %), reacts (25 %), reads polls (10 %) as 500 different signed-in users |
| 7 | **notify** | one goal fanned out to every follower of the most-followed team (9,076 recipients), in process, through the real dispatcher with the network senders replaced by counters |

## Results — 1 uvicorn worker (the container default)

| scenario | peak VUs | req/s | p50 | p95 | p99 | 5xx/transport errors | api CPU (cores avg) | api RAM peak | PG connections (active) | Redis MB / clients | Celery queue max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| home | 25 | 38.8 | 35 ms | 316 ms | 838 ms | 0 | 0.47 | 154 MB | 5 (1) | 2 / 25 | 0 |
| live | 100 | 50.9 | 244 ms | 1,100 ms | 1,460 ms | 0 | 0.94 | 160 MB | 12 (1) | 3 / 31 | 0 |
| search | 100 | 54.8 | 367 ms | 1,470 ms | 2,200 ms | 0 | 0.94 | 162 MB | 12 (1) | 5 / 34 | 0 |
| spike | 400 | 67.4 | 1,280 ms | **8,780 ms** | 10,350 ms | **45 (0.92 %)** — 503 from pool wait | 0.89 | 184 MB | 21 (3) | 4 / 40 | 0 |
| community | 100 | 39.6 | 24 ms | 233 ms | 457 ms | 0 | 0.65 | 184 MB | 11 (2) | 3 / 37 | 0 |
| websocket | 1,000 held | — | connect p50 5 ms | connect p95 102 ms | connect p99 148 ms | 0 dropped | 0.42 | 197 MB | 11 (1) | 3 / 37 | 0 |

## Results — 3 uvicorn workers (`WEB_CONCURRENCY=3`)

| scenario | peak VUs | req/s | p50 | p95 | p99 | 5xx/transport errors | api CPU (cores avg) | api RAM peak | PG connections (active) | Redis MB / clients | Celery queue max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| home | 25 | 40.1 | 27 ms | 130 ms | 228 ms | 0 | 0.70 | 439 MB | 9 (1) | 2 / 38 | 0 |
| live | 100 | 61.1 | 22 ms | 331 ms | 708 ms | 0 | 1.01 | 447 MB | 19 (1) | 3 / 39 | 0 |
| search | 100 | 70.8 | 41 ms | 748 ms | 1,287 ms | 0 | 1.39 | 459 MB | 20 (2) | 5 / 46 | 0 |
| spike | 400 | **106.1** | **674 ms** | **2,915 ms** | 4,216 ms | **0** | 1.64 | 481 MB | 44 (4) | 5 / 61 | 0 |
| community | 100 | 39.7 | 17 ms | 339 ms | 867 ms | 0 | 0.75 | 481 MB | 31 (1) | 4 / 69 | 0 |
| websocket | 1,000 held | — | connect p50 5 ms | connect p95 62 ms | connect p99 114 ms | 0 dropped | 0.48 | 500 MB | 31 (1) | 3 / 69 | 0 |

*Reading the two tables together.* `home`, `community` and `websocket` are limited by the virtual users' think time, not by the server — the server has headroom there (0.4–0.7 cores).
`live`, `search` and especially `spike` are where one worker runs out: it saturates at ≈ 0.9 of one core, requests queue behind each other (p95 8.8 s in the spike) and 0.9 % are shed with 503 when
the connection pool wait expires. Three workers handled the same 400-user surge with **no errors, p50 674 ms, p95 2.9 s, +57 % throughput** — scaling is by CPU, as designed. The database never was
the limit: **PostgreSQL averaged 0.03–0.25 cores and 1–4 active connections** in every run; Redis used 2–5 MB; the Celery queue stayed empty.

### Capacity probes (closed loop, no think time, 50 virtual users, 1 worker)

| probe | req/s | p50 | p95 | what it isolates |
|---|---|---|---|---|
| `GET /health/live` | **342** | 100 ms | 274 ms | framework + middleware only (≈ 2.9 ms of CPU per request) |
| `GET /matches/{id}/head-to-head` (cached) | **189** | 221 ms | 414 ms | a typical Redis-cached read (≈ 5.3 ms) |
| `GET /search?q=arsenal` (cached, same query) | **107** | 379 ms | 648 ms | the Phase 7 search cache hit path |
| `GET /search?q=<new>` (always a miss) | **75** | 522 ms | 1,050 ms | search computed from Postgres |

(Latency at 50 closed-loop users is queueing delay: 50 requests are always in flight against one core. The throughput column is the capacity figure.)

### Notification fan-out (scenario 7), 9,076 recipients

| | Before | After |
|---|---|---|
| Result | **failed outright** above ≈ 8,000 followers (bind-parameter limit) — nobody notified | works |
| SQL statements | 36,315 (4 per recipient) | 16 |
| Time (network senders stubbed) | 130.7 s (5.3 resolve + 125.4 delivery) | **6.0 s (5.35 resolve + 0.65 delivery)** |
| Push requests to Expo | 1 TLS connection per device | batches of 100 on one connection pool (≈ 46 requests for 4,538 devices) |

Real delivery adds Expo/web-push latency, now batched and concurrent (the 300-second task limit is far above the ≈ 6 s database part).

### Cold cache

Right after a Redis flush the first requests for each match variant compute from Postgres: `form`, `head-to-head` and `insights` cost ≈ 30–40 ms of CPU each (about 25 req/s per worker while
the 1,600 distinct match/variant keys in the test warm up). Warm, the same endpoints cost ≈ 5 ms. Only matches people are looking at get hot, so a real spike warms in seconds; if cold-start latency
ever matters, pre-warm the live matches' keys from the sync task.

## What load testing changed (each is a code change with a test)

| Finding | Measured effect |
|---|---|
| Unified search had no cache and was the first endpoint to saturate | 11.3 → **54.8 req/s**, p50 5.4 s → **0.37 s** at 100 users on one worker |
| Notification fan-out N+1 and the bind-parameter failure | see above |
| Missing index on `refresh_tokens.replaced_by_id` (found by the housekeeping job timing out) | 186 s → 1.2 s |
| Stopping Redis under load froze the API (found by the failure tests, not the load tests) | fixed — `docs/operations/failure-modes.md` |
| Reads that called the football provider | removed |

*Tried and rejected:* turning the ~27 synchronous FastAPI dependency factories into `async def` to avoid thread-pool hops. An A/B test (same scenario, 100 users) showed no measurable gain
(p95 1.32 s vs 0.63 s in favour of the original — run-to-run noise on this machine), so the code was left alone.

## Reproduce

```bash
python apps/api/scripts/make_loadtest_data.py --dsn postgresql://… --out load/k6/world.json       # ids + tokens
POSTGRES_DB=football_perf WEB_CONCURRENCY=1 docker compose up -d --force-recreate api worker scheduler
load/run-suite.sh "1 uvicorn worker" load/results/1w && python load/summarize.py load/results/1w "1 uvicorn worker"
load/run-k6.sh spike 100 30s                      # one scenario; SCENARIO=ping|cached|searchhot|searchcold for the probes
python apps/api/scripts/loadtest.py --scenario notify --pg-dsn …   # the fan-out
```
Thresholds baked into the k6 script (p95 < 1 s, error rate < 1 %, < 50 server errors) make a run exit non-zero in CI-style use; the suite records results regardless.
