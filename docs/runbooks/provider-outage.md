# Football data provider outage or quota exhaustion

**Symptoms.** `FootballLiveDataStale` (a live match not synced for > 5 min), `FootballProviderFailing` (> 50 % of provider
requests failing), `provider_rate_limited_total` rising, matches carrying `data_status: STALE`.

**Impact.** The API keeps serving everything it has stored — **reads never call the provider**, so no endpoint errors because
of an outage. Scores and fixtures stop moving; each match is marked `STALE` (web and mobile show how old it is; mobile's
banner says "Scores last updated 14:02 (6 min ago)"). Search with no local match returns an empty result instead of an
error. Notifications for new events stop (nothing new is detected).

## Diagnose

1. `GET /api/v1/admin/system` → `provider` (requests / errors / rate_limited counters) and `data_freshness`.
2. Worker log: `$C logs --tail 200 worker | grep -iE "provider|rate-limited|ProviderUnavailable|quota"`.
   * `429` / "quota" → you ran out of requests (daily quota on the free tier is small). Polling cadence is
     `LIVE_POLL_INTERVAL_SECONDS` (30), `UPCOMING_POLL_INTERVAL_SECONDS` (60); the guard backs off exponentially
     (`SYNC_BACKOFF_SECONDS` × 2ⁿ) and gives up a cycle after `SYNC_MAX_RETRIES`, never hammering a failing provider.
   * `401/403` → the API key was rotated or revoked (the failure is classified *authentication* and is **not** retried:
     look in `GET /api/v1/admin/failed-jobs`).
   * timeouts / 5xx → the provider itself is down; check its status page.
3. Did a restart storm spend the quota? Start-up only re-syncs when data is older than 12 h (`seed_database`), so restarts
   no longer cost provider requests.

## Fix

| Cause | Action |
|---|---|
| Provider down | nothing to do but wait; sync resumes by itself. Post a status note if matches are live. |
| Quota exhausted | lengthen the poll intervals (`LIVE_POLL_INTERVAL_SECONDS=60`), restrict `FOOTBALL_API_LEAGUE_IDS`, or upgrade the plan |
| Key invalid | set the new `FOOTBALL_API_KEY` in `.env.production`, `$C up -d api worker scheduler`; then resolve the failed jobs |
| Switching provider | implement `FootballDataProvider` (the abstraction in `app/services/providers/base.py`) and set `FOOTBALL_DATA_PROVIDER` |

## Verify

`football_live_data_age_seconds` back under 120; matches no longer `STALE`; `provider_errors_total` flat.

## Afterwards

Resolve the related entries in `GET /api/v1/admin/failed-jobs` (`POST …/resolve` with a note — the action is audit-logged).
