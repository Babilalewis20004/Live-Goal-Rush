# Community: comments, reactions, polls, profiles, moderation

Phase 6a built the community features; Phase 6b widened reactions, added profile reporting and account
suspension, community signals in the feed, and real-time nudges. All of it reuses article ids and match ids —
there is one comment architecture, with `target_type ∈ {article, match}`.

## Comments (`/api/v1/comments`)

* Plain text only. Bodies are stored and rendered as text (React escapes; never `dangerouslySetInnerHTML`). Max
  2000 characters, at most 2 links; whitespace is normalised.
* One level of replies (`parent_id` of a top-level comment). Replying to a reply attaches to the same thread.
* Edit/delete your own; moderators can hide, restore or delete anyone's. A deleted parent with replies shows a
  tombstone.
* **Spam and abuse controls** (all configurable, see `.env.example`): sign-in required to post; per-user rate
  limits (5/min, 40/h, Redis); accounts younger than 10 minutes cannot post links; identical repeats are refused;
  3 independent reports auto-hide a comment pending review. Suspended accounts cannot authenticate at all.
* Pages are cached **viewer-independently** under a per-target version and the viewer's own likes/"mine" flags are
  overlaid afterwards, so one user's state can never leak into another's page.

## Reactions (`/api/v1/reactions/{article|match}/{id}`)

Seven kinds: 👍 `thumbs_up`, 🔥 `fire`, 😮 `wow`, ⚽ `goal`, ❤️ `heart`, 😂 `laugh`, 👏 `clap`. One reaction per
person per target (unique constraint) — picking another replaces yours, picking yours removes it. Counts are a
Redis hash rebuilt from PostgreSQL on a miss; the database is the source of truth.

## Polls (`/api/v1/polls`, editors create via `/editor/polls`)

Match, article-attached or standalone. One vote per user (unique constraint), cannot be changed; optional
`closes_at`; a beat job closes due polls (atomic `UPDATE … RETURNING`, idempotent) and announces results to the
people who voted. Results show counts, percentages and the leader in words.

## Profiles

Private by default. A user can opt in to a public page (display name, bio, favourites, badges, recent comments on
public content). A private profile answers 404 — indistinguishable from a missing one, so profiles cannot be
probed for existence. Nothing private (email, role) is ever in a public profile.

## Reporting and moderation

| Who | Can |
|---|---|
| Any signed-in user | report a comment; report a **public** profile (once each, optional 200-char reason; not your own) |
| Editor / Admin | list open/resolved/dismissed comment and profile reports, hide / restore / delete comments, resolve or dismiss profile reports |
| Admin only | `POST /moderation/users/{id}/suspend` / `unsuspend` |

Suspension (`users.suspended_at`) is checked wherever identity is resolved: bearer/cookie authentication returns
"anonymous" for a suspended user (so every protected call is 401), sign-in is refused with 403 *only after the
password has been verified* (so a stranger cannot learn an account is suspended), token refresh fails, and all
refresh tokens are revoked at suspension. Admins cannot suspend themselves or other admins.

Profile-report endpoints rate-limit per IP (`PROFILE_REPORTS_PER_HOUR`).

## Community signals in the feed (Part D)

`DiscoveryService._build_feed` gained two deterministic, explainable signals from the last 14 days:

| Reason | Tier | Meaning |
|---|---|---|
| `community_match` | 4 (same as upcoming followed games; below live and today's) | a live/upcoming match you commented on, reacted to or voted in a poll for — "You joined the conversation on A v B" |
| `community_article` | 7 (with searched news; above trending) | a published article you commented on, reacted to or voted in — "You commented, reacted or voted here recently" |

Followed teams/competitions and view history keep their tiers; there is no learned ranking. Viewed matches are not
a signal because views are stored as anonymised aggregate counters, not per user (a deliberate privacy choice).

## Notifications

Kinds (preferences at `/notifications/content-preferences`): `comment_replies` (default **on**),
`editorial_updates` (on), `poll_results` (off), plus Phase 6b `prediction_available`, `team_insights`
(matchday reminder), `poll_closing` (all off) and `subscription_events` (**on** — about your own account). Every
send goes through `social_notification_service.deliver`: preference check → unique `(user, dedup_key)` claim →
send; nobody is notified about their own action; relevance comes from favourites. Quiet hours: not supported in
this codebase, so not implemented.

## Real-time

`comment.created`, `comment.reaction`, `poll.updated` (match-scoped) are published on the existing
`football:events` channel with **ids only** — clients refetch through the normal permission-checked API.
They are throttled to one per type per match per 2 s, delivered only to sockets watching that match (never the
general livescore feed), and the clients route them to a counter instead of the score reducer.

## Privacy

Collected for community: the content a user posts, their reactions and votes (needed to enforce one-per-user),
and report rows (reporter id, reason). Activity is only visible on a public profile and only for public content.
Reactions/votes are never listed per person. Retention: until the user or content is deleted (foreign keys
cascade); no extra analytics are collected about reading.
