# Phase 6 — Advanced Analytics, Predictions/Insights, Social/Community & Monetisation

> Naming: the repository already used "Phase 5" twice — once for overrides/season history/metrics
> ([phase5.md](phase5.md), untouched) and once for the *discovery* work ([discovery.md](discovery.md)).
> This document describes **Phase 6**, which was delivered in two passes on the same migration chain:
> **6a** media platform, editorial workflow, community and observability; **6b** analytics, predictions,
> persisted insights, billing/entitlements, ads and the community-aware feed.

Nothing from Phases 1–5 was rebuilt. Every new piece sits on the existing seams: SQLAlchemy/Alembic,
`CacheAside`, Celery + beat, the Redis pub/sub → WebSocket bridge, the `NotificationService`
pipeline, the provider abstraction and the shared `Metrics` registry.

## Architecture assessment (what existed → what Phase 6b did with it)

| Concern | Found in the repository | Phase 6b decision |
|---|---|---|
| Team statistics | `match_statistics` rows per match/team; `team_statistics` endpoint (standings-based) | **Extended**: `AnalyticsService` aggregates the stored rows over a window. No new statistics tables. |
| Player statistics | `player_match_statistics`, `player_season_statistics` | **Extended**: per-90, history, trend. |
| Form / head-to-head | `FormService` (last 5, last 5 meetings) | **Extended in place**: 5/10 windows, streaks, `complete`/`limitation`, H2H windows + goals. Old endpoints keep their shape (additive fields only). |
| Insights | `InsightsService` (sentences from form + H2H, cached, not stored) | **Extended**: `InsightGenerator` persists them with a data version; live and player insights added. |
| Predictions | none | **New** (`analytics_math.predict`, `PredictionService`, `predictions`/`prediction_evaluations`). |
| Comments / reactions / polls | complete from 6a | Reactions widened (7 kinds); profile reports and account suspension added. |
| Subscriptions / payments / ads | **none** | **New** provider-independent billing, entitlements, ad eligibility. |
| Notifications | `ContentNotificationKind` + `social_notification_service.deliver` (preferences, dedup log) | **Reused**: four new kinds, no second pipeline. |
| Real-time | `football:events` pub/sub → `ConnectionManager` | **Reused**: five `RealtimeEventType` values, delivered to the match's sockets only. |
| Metrics | `Metrics` + Redis aggregation + Prometheus/Grafana (6a) | **Reused**: 13 new counters, a dashboard and three alerts. |
| Infrastructure | Postgres, Redis, Celery worker + beat, MinIO, Prometheus, Grafana | **Unchanged.** No new service was added. |

## Data flow

```
 football provider ──► sync workers ──► PostgreSQL (matches, match_statistics, player_*_statistics)
                                             │
              ┌──────────────────────────────┼──────────────────────────────────┐
              ▼                              ▼                                  ▼
   AnalyticsService (SQL aggregates)   PredictionService (Poisson)    InsightGenerator (sentences)
   cached: team/player/comparison      stored + evaluated              stored with source_data_version
              │                              │                                  │
              └──────────── FastAPI (entitlement-shaped responses) ◄───────────┘
                                   │                        ▲
                     Redis pub/sub nudges ──► WebSocket     │ Celery beat (predictions, evaluation,
                     (match page only)                      │ insights, warm-up, matchday, billing tidy)
                                   ▼
                          web (Next.js) / mobile (Expo)
```

## Where things live

| Area | Backend | Web | Mobile |
|---|---|---|---|
| Analytics maths | `services/analytics_math.py` | `lib/analytics.ts` | `src/lib/analytics.ts` |
| Team/player analytics, comparison | `services/analytics_service.py`, `api/v1/analytics.py` | `components/analytics/*` | `src/components/analytics/*` |
| Predictions | `services/prediction_service.py`, `models/analytics.py` | `prediction-card.tsx` | `prediction-card.tsx` |
| Insights | `services/insight_records.py`, `personal_insights.py` | `analysis-tab.tsx`, `personal-insights.tsx` | same names |
| Billing / entitlements | `services/billing/*`, `api/v1/billing.py` | `components/premium/`, `app/premium` | `src/app/premium.tsx` |
| Ads | `services/ads.py` | `ad-slot.tsx` | `ad-slot.tsx` |
| Moderation | `services/moderation_service.py`, `api/v1/profiles.py` | `profile-reports.tsx`, `report-profile.tsx` | `report-profile.tsx` |
| Jobs | `worker/analytics_tasks.py`, `worker/schedule.py` | | |

## Documents

* [analytics.md](analytics.md) — calculations, tiers, caching, honesty rules
* [predictions.md](predictions.md) — the model, storage, evaluation, limits
* [community.md](community.md) — comments, reactions, polls, reports, suspension, feed signals
* [monetisation.md](monetisation.md) — plans, entitlements, checkout, webhooks, ads, privacy, security
* [media.md](media.md), [editorial-workflow.md](editorial-workflow.md), [observability.md](observability.md) — Phase 6a
* [security-phase6.md](security-phase6.md) — security and privacy review

## Database changes

* 6a — `e6a1c0de0601`: `media*`, `article_revisions`, `comments`, `comment_likes`, `comment_reports`,
  `reactions`, `polls`, `poll_options`, `poll_votes`, `social_notification_log`; article scheduling columns;
  `users.profile_public`, `users.bio`.
* 6b — `a7c3d9e1b402` (revises `e6a1c0de0601`, additive only): `predictions`, `prediction_evaluations`,
  `insights`, `subscription_plans`, `subscriptions`, `entitlements`, `payment_events`, `profile_reports`;
  `users.suspended_at`, `users.suspended_reason`; indexes `ix_match_statistics_team`,
  `ix_player_match_statistics_team`. See [database.md](database.md).

## Known limitations

See the README's *Known limitations* and the per-document "Limits" sections. The important ones:
predictions are a simple Poisson model with no evidence yet of how good they are; xG, xA and progressive
passes exist only where the provider's data supplies them (the schema has an xG column; the others are not
stored); the Stripe adapter has not been exercised against a live Stripe account; mobile subscribes via
the website because app-store in-app-purchase rules are a separate product decision.

## Brief items deliberately not built (and why)

| Item | Status |
|---|---|
| `TeamAnalytics` / `PlayerAnalytics` tables | Not created: the numbers are aggregates of rows already stored; a second copy would only go stale. They are computed, cached and warmed by `calculate_team_analytics`. |
| Separate `CommentReply` / `CommentReaction` models | Replies are comments with a `parent_id`; "reacting" to a comment is a like (`comment_likes`); the emoji reactions apply to articles and matches. One architecture, not two. |
| Team "form trajectory" / player "expected contribution" predictions | Not built: the stored data cannot support an honest estimate. Only match result and goals are predicted. |
| "Your favourite *player* scored" insight | There is no favourite-players concept in the product; favourite teams and competitions drive personal insights. |
| Notifications for *comment reactions* and *insight generated* | Not sent (they would be high-volume and low-value); replies, estimates, matchday, poll closing/results, editorial and subscription events are. |
| Quiet hours | Not supported anywhere in the codebase, so not implemented. |
| `aggregate_community_metrics` job | Not needed: community counters are incremented inline and aggregated across processes by the existing Redis sink. |
| Per-job duration histograms | Failure counters and queue length exist; duration histograms for the new tasks do not. |
| Viewed matches as a feed signal | Views are anonymised aggregate counters by design, so they cannot personalise. |
| UI end-to-end automation | No Playwright/Detox in the repository; the journey is covered by API integration (`test_phase6b_e2e.py`), component tests and a manual Docker run. |
