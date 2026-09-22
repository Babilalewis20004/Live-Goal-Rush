# Notification Architecture (Phase 3)

## The goal

> When something happens to a match a user follows (a goal, kick-off,
> full-time...), that user gets a push notification — on every device
> they've registered, exactly once, regardless of provider retries,
> Celery retries, or a worker restart mid-cycle.

Phase 2 already built the pipeline this reuses in full: adaptive polling →
change detection → an internal `RealtimeEvent` stream on Redis Pub/Sub
(`docs/architecture/realtime.md`). Phase 3 does **not** introduce a second
polling system or a parallel event model — it adds a second, independent
consumer of the exact same stream.

## Pipeline

```
Football Provider
       │
       ▼
Celery worker (sync + change detection, unchanged from Phase 2)
       │
       ▼
_publish_changes() -- for each RealtimeEvent:
       │
       ├──► redis.publish(MATCH_EVENTS_CHANNEL, event)  (Phase 2, unchanged)
       │           │
       │           ▼
       │    WebSocket pub/sub bridge → ConnectionManager → live UI
       │
       └──► dispatch_notifications.delay(event)  (Phase 3, new)
                   │
                   ▼
       notification_dispatch_service.resolve_targets(db, event)
         1. load the Match (home/away team ids, competition id)
         2. one query per favourite table, filtered to *this match's*
            ids -- O(favouriters of this match), never O(all users)
         3. match candidates against NotificationPreference overrides
            (explicit opt-out/opt-in; GLOBAL mute wins outright)
         4. atomic dedup claim: one bulk
            INSERT ... ON CONFLICT (user_id, dedup_key) DO NOTHING
            RETURNING user_id
                   │
                   ▼
       NotificationService.send_to_user() per claimed target
         -- loads that user's Device rows, sends via the matching
            PushSender (Expo or Web Push), removes devices the
            provider reports as permanently gone
```

`worker/tasks.py::_publish_changes` is the only place these two paths
share code, and even there `dispatch_notifications.delay(...)` is wrapped
in a `try/except` so a broker hiccup can never break the live-sync loop —
notification dispatch runs as its **own** Celery task with its **own**
retry policy (`bind=True, max_retries=3` in
`worker/notification_tasks.py`), completely decoupled from
football-provider sync retries. The WebSocket layer is never involved in
notification delivery, and the notification pipeline never touches
`ConnectionManager` — two independent consumers of one event stream, per
spec.

## Preference matching

Reuses `RealtimeEventType` (the same provider-agnostic enum the real-time
pipeline already publishes) as `NotificationPreference.event_type` —
there is exactly one vocabulary for "what happened to a match" in this
codebase, not a parallel notification-specific type.

**Default-on set** (`notification_dispatch_service.DEFAULT_ON_EVENT_TYPES`):
`MATCH_STARTED`, `GOAL`, `CARD`, `HALF_TIME`, `MATCH_FINISHED`. Everything
else (`MATCH_UPDATED`, `SUBSTITUTION`, `SECOND_HALF_STARTED`,
`MATCH_POSTPONED`, `MATCH_CANCELLED`) is default-**off** — mostly noise —
and only fires for a user with an explicit `enabled=True` preference row.

Favouriting a team/competition/match implies the default-on notifications
for it, without writing any preference rows — a preference row only
exists to *override* a default. Effective state for a given
`(user, scope, event_type)` is: the explicit row's `enabled` if one
exists, else the default. A `GLOBAL` (`scope_id IS NULL`) mute for an
event type wins outright over every other qualifying scope. The database
enforces true one-row-per-`(user, scope, event_type)` uniqueness even for
`GLOBAL`'s `NULL scope_id` via `postgresql_nulls_not_distinct=True` (plain
Postgres uniqueness otherwise treats every `NULL` as distinct from every
other `NULL`).

## Idempotency / deduplication

`notification_log`'s `UniqueConstraint(user_id, dedup_key)` is the entire
mechanism. `dedup_key` is deterministic per event:

- Event-scoped types (`GOAL`, `CARD`): the underlying `MatchEvent.id`
  already present in the `RealtimeEvent`'s `data["event"]["id"]` (see
  `change_detection.py::_event_added`) — stable even if the same event is
  re-published.
- Status-transition types (`MATCH_STARTED`, `HALF_TIME`,
  `MATCH_FINISHED`): `f"{match_id}:{event_type}"` — change detection only
  ever fires one of these per actual transition.

A duplicated provider event, a retried Celery task, a worker restart
mid-cycle, and a genuinely re-detected identical event all reduce to the
same case: the `(user_id, dedup_key)` row already exists, so the bulk
`INSERT ... ON CONFLICT DO NOTHING RETURNING user_id` simply doesn't
return that user, and no second push is sent. No separate
check-then-insert step, so there's no race window between two workers
processing the same event concurrently either.

## Delivery abstraction

`app/services/notifications/` mirrors `app/services/providers/`'s style:
business logic depends only on the abstract `PushSender` (`base.py`),
never on Expo/Web Push specifics.

- `expo_sender.py` — Expo's push API (`https://exp.host/--/api/v2/push/send`).
  Works without separate FCM/APNs credentials in this environment; the
  Expo project only needs linking to an EAS project (external, one-time,
  `expo.dev`-account step) for the *client* to obtain a real push token —
  server-side delivery has no such dependency once a token exists.
- `web_sender.py` — Web Push via VAPID (`pywebpush`), no external account
  needed; generate a keypair locally (see `apps/api/.env.example`).

Both report `DeliveryResult(success, should_remove_device)` —
`should_remove_device=True` (an Expo `DeviceNotRegistered` error, or a
404/410 from the Web Push endpoint) means the token/subscription is
permanently gone, and `NotificationService` deletes that `Device` row.
Any other failure is treated as transient and retried a few times with
backoff inside the sender itself, without touching the `Device` row.

## Device management

`devices` — one row per registered push target (Expo token, or a Web Push
subscription triple), never both on the same row. A user may have several
(phone, tablet, browser). A push token belongs to exactly one row
globally (partial unique indexes on `expo_push_token`/`web_push_endpoint`,
each only where non-null); re-registering an already-known token
reassigns it to the current user rather than erroring — handles both a
token refresh and a different user signing in on a shared device.

## API

```
GET/PATCH /api/v1/notifications/preferences
GET       /api/v1/notifications/vapid-public-key
POST      /api/v1/notifications/web-push/subscribe
GET/POST  /api/v1/devices
DELETE    /api/v1/devices/{device_id}
```

## Mobile push (Expo)

`apps/mobile/src/lib/push-notifications.ts::registerForPushNotificationsAsync`
runs once after login (or session restore) succeeds — an anonymous user
has no `Device` row to attach a token to. Requests permission, obtains an
Expo push token, registers it via `POST /api/v1/devices`. Degrades
gracefully (logs a warning, returns) when there's no physical device or
no EAS `projectId` configured, rather than throwing. Tap handling
(`addNotificationResponseListener`, mounted once from the root layout)
reads the same `{type, id}` payload the backend builds and navigates
using the existing Expo Router paths (`match/[id]`, `team/[id]`,
`competition/[id]`) — no new navigation structure needed.

## Web push

`apps/web/public/sw.js` (hand-rolled, no `next-pwa` — consistent with this
repo's existing hand-rolled `RealtimeConnection` client style) handles the
`push` event (shows the notification) and `notificationclick` (focuses or
opens the right `/match/{id}` etc. page, same `{type, id}` contract as
mobile). `apps/web/lib/push.ts::subscribeToPush()` does the full round
trip: permission prompt → fetch the VAPID public key from the backend →
`pushManager.subscribe` → register the subscription as a `Device`. Never
mandatory — the app works identically with push declined or unsupported.

## Reliability

- Notification dispatch is a separate Celery task from sync, with its own
  retry policy — a slow/failing push provider can never slow down or
  crash the live-sync loop.
- Every Redis/DB operation in this path either fails open (rate limiting,
  the `sync_team.delay()` on-follow trigger) or is wrapped so a partial
  failure logs and continues rather than raising into the API/worker.
- Metrics: `notifications_sent_total`, `notifications_failed_total`,
  `notifications_deduplicated_total` (`app/services/metrics.py`, same
  pattern as every other Phase 2 counter).

## Database

`devices`, `notification_preferences`, `notification_log` — see
`alembic/versions/490ba085e61c_phase_3_notifications.py` for the full
schema and constraint rationale.

## Tests

`apps/api/tests/test_notification_dispatch.py` — fan-out across
team/competition/match favourites, explicit opt-out, global mute
override, default-on vs default-off event types, dedup-on-redelivery, and
a query-count assertion proving the design doesn't scale with unrelated
user count. `apps/api/tests/test_notification_delivery.py` — multi-device
fan-out, stale-device removal on a permanent failure, and that a
transient failure leaves the device registered. `apps/api/tests/
test_devices_and_preferences_api.py` — the REST endpoints, including
cross-user isolation and the `GLOBAL`-scope idempotent upsert.
