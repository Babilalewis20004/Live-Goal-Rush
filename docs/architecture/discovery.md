# Discovery: news, search, trending and the personalised feed

> **Naming note.** This repository already uses "Phase 5" for an earlier,
> unrelated piece of work (per-favourite notification overrides, season history,
> cross-process metrics — see [phase5.md](phase5.md)). This document covers the
> *discovery* brief, which was also called "Phase 5". The code, migration
> (`d56d209c5f0e_phase5_discovery.py`) and tests (`test_news_content.py`,
> `test_discovery_*.py`, …) refer to it as *discovery*.

LivePitch started as a livescore platform. Discovery turns it into a place to
find football: news that is linked to the real teams/players/competitions/matches
already in the database, one search box across all of it, "what is getting
attention right now", and a feed that puts what *you* follow first. Anonymous
visitors get all of the public parts; personalisation only ever adds.

PostgreSQL and Redis do all of it, through the existing Celery worker. No new
infrastructure (no Elasticsearch, no queue, no recommendation service).

```
                         ┌──────────────────────────── web / mobile ────────────────────────────┐
                         │ home · news · article · search · team/competition/player/match News │
                         └───────────────▲──────────────────────────────────────────────────────┘
                                         │ REST (+ the existing WebSocket for live matches only)
        ┌────────────────────────────────┴───────────────────────────────┐
        │ FastAPI:  /articles  /editor/articles  /discovery  /feed        │
        │           /search*  /engagement/view  /…/{id}/news              │
        └───────┬──────────────────────┬──────────────────────┬──────────┘
                │ reads/writes         │ counters, caches     │ enqueue
        ┌───────▼───────┐      ┌───────▼────────┐     ┌───────▼────────┐
        │  PostgreSQL   │◄─────┤     Redis      │◄────┤ Celery worker  │
        │ articles, tags│ agg. │ view counters, │     │ + beat:        │
        │ engagement_*  │      │ trending, feed │     │ aggregate (1m) │
        │ recent_search │      │ & list caches  │     │ trending (5m)  │
        └───────────────┘      └────────────────┘     │ notify (on pub)│
                                                      └────────────────┘
```

---

## 1. News

### Model (`app/models/article.py`)

| Table | Purpose |
|---|---|
| `articles` | `slug` (unique, **stable** — never changes when the title is edited), `title`, `excerpt`, `content` (sanitized HTML), featured image URL + alt, `author_id`, `status`, `published_at`, `is_featured`, `category_id`, `view_count`, `notified_at` |
| `article_categories` | `slug`, `name`, optional `competition_id` |
| `article_tags` | `slug` (unique ⇒ "Real Madrid" and "real  madrid" are one tag), `name` |
| `article_tag_links`, `article_teams`, `article_players`, `article_competitions`, `article_matches` | many-to-many links, `ON DELETE CASCADE`, indexed by the **entity** id (the hot direction: "articles about team X") |

Articles *link to* the existing `Team`/`Player`/`Competition`/`Match` rows. Nothing
about football is copied; the editor can only link ids that exist (unknown ids are
rejected with a 422 naming them).

`status` is `DRAFT → PUBLISHED → ARCHIVED`. **One predicate defines "public"**
(`ArticleService._public()`: `PUBLISHED` and `published_at <= now()`) and every
public read — list, detail, related, per-entity news, search, suggestions,
trending, feed — goes through it, so a draft cannot leak through a side door
(there is a test for each path). Unpublishing/archiving takes effect immediately
(the cache is versioned, §6).

**Categories** are data, not code: `ensure_default_categories` creates four generic
ones (Football News, Transfers, Match Reports, International Football) plus **one
per synced competition**, pointing at the real `Competition` row — so "Premier
League" news is also the competition page's news, and categories follow the
football data. Clients read `/articles/categories`; nothing is hard-coded in the UI.

**Tags** are reusable (upsert on the unique slug) and capped at 10 per article.

### Authoring and authorization

There was no admin system in the repo, so this adds the smallest one that is safe:

* `users.role` — `user` (default) / `editor` / `admin`. **Not self-service**: roles
  are granted by an operator, `python -m app.cli set-role someone@example.com editor`.
* `EditorDep` (403 unless editor/admin) guards `/api/v1/editor/articles*`; on top of
  that `ArticleService` enforces ownership — **an editor can only read, edit, publish,
  archive or delete their own articles; an admin can touch all**. The router never
  decides ownership. Only admins create categories.
* Workflow endpoints: create (draft or straight to published), `PATCH` (only the
  fields sent), `publish`, `unpublish` (→ draft), `archive`, `DELETE`.
* The web has a role-gated editor UI (`/editor`, `/editor/new`, `/editor/[id]`):
  headline, summary, HTML body, featured image URL + alt text, category, tags,
  featured flag, and an entity picker that searches the real catalogue. Mobile does
  not author (documented limitation).

### HTML safety (`services/html_sanitizer.py`)

Editor HTML is never trusted. It is parsed with `html.parser` and **rebuilt from an
allow-list**: tags `p br h2 h3 h4 strong b em i u ul ol li blockquote a img hr`;
attributes only `href`/`title` on `a` and `src`/`alt`/`title` on `img`; URL schemes
only `http`, `https`, `mailto` (links) and `http`/`https` (images), same-site paths
for links; `script/style/iframe/object/embed/svg/math/form/…` are removed *with
their contents*; comments are dropped; every text node and attribute is escaped;
links get `rel="noopener noreferrer nofollow"`; images get `loading="lazy"` and a
non-null `alt`. Because the parser decodes entities first, `jav&#x61;script:` and
`java\tscript:` are caught by the URL check. It runs on **every write**, so what is
stored is always safe to emit; the API also returns `content_text` and typed
`content_blocks` (heading / paragraph / list_item / quote) for clients without an HTML
renderer. 29 tests, including the classic bypass list.

**Images** are URLs only: the server never fetches them (no SSRF), only `http(s)` is
accepted, `ARTICLE_IMAGE_ALLOWED_HOSTS` can restrict hosts, and alt text always
exists (defaults to the headline). There is no upload/storage subsystem in this
repo, so file-type/size validation of uploads does not apply — see Limitations.

### Discovery of articles

`GET /articles` — latest, with `category`, `tag`, `featured`, `team_id`, `player_id`,
`competition_id`, `match_id` filters. `GET /teams|players|competitions|matches/{id}/news`.
All return the repository's `Page{items,total,page,page_size}` and are `EXISTS`-based
SQL with `LIMIT/OFFSET` (never filtered in Python). Author payloads carry only the
display name, never an email.

**Match news** is *match → team → competition* and nothing else; each item carries
`relation` so the UI can say "About this match" / "Team news" / "Competition news".
Entity pages only show a News tab when there is something linked to show.

### Related articles (`ArticleService.related`)

Deterministic and explained. For a source article, up to 200 recent published
candidates that share *something* are scored:

| shared | points |
|---|---|
| competition (direct link or category's competition) | 8 |
| team | 6 |
| player | 5 |
| match | 4 |
| category | 3 |
| tags | 2 each, max 3 tags |
| recency | up to 2, `2 / (1 + age_days/7)` |

Ties break on newest. Each result has a `reason` such as "Same competition, same
team". Cached per version; a cached id list can never resurrect an unpublished
article because the cache is invalidated on every change.

---

## 2. Search

`GET /api/v1/search?q=&limit=` returns `teams`, `competitions`, `players`,
`matches`, `articles` (the original four keys are unchanged; `articles` is new).

### Engine and indexing

PostgreSQL only. `pg_trgm` GIN indexes (`ix_teams_name_trgm`, `ix_players_name_trgm`,
`ix_competitions_name_trgm` from the match-centre migration, and
`ix_articles_title_trgm` added here) make `ILIKE '%q%'` and the trigram `%` operator
index-assisted; matches use the existing `(home|away)_team_id` indexes; articles also
have `(status, published_at)`, `(category_id, published_at)` and a partial index for
the featured shelf.

### Ranking (`services/search_ranking.py`)

Within each group: **exact (0) → prefix (1) → contains (2) → fuzzy (3)**, then trigram
`similarity()` descending, then name. Teams also match their short code ("ARS") by
prefix. Articles match title, excerpt (≥3 chars) and tag names; the title tier wins.
Rules that keep results small and relevant:

* groups are capped (default 10, max 20 via `limit`) — never hundreds of rows;
* 1–2 character queries are **prefix-only** (no fuzzy), `%`/`_`/`\` are escaped so a
  wildcard is literal text;
* matches are those of the best three matching teams, nearest to "now" first;
* the provider fallback (when nothing local matches) is **not** used for queries under
  3 characters, so public traffic can't drain provider quota with probes.

### Suggestions, popular, recent

* `GET /search/suggestions?q=` (≥2 chars): up to 8 typed suggestions (team, competition,
  player, article), best match quality first; cached 120 s per normalised prefix.
* `GET /search/popular`: a per-day Redis sorted set. It is fed **only when a visitor
  chooses a result** (`POST /search/track` with an entity), one vote per visitor per
  query per day, and a phrase is only listed once `POPULAR_SEARCH_MIN_VIEWERS` (3)
  different visitors agree — one person's private phrase can't be published.
* `GET/DELETE /search/recent`: signed-in users' own history in `recent_searches`
  (newest 10, case-insensitively unique, `ON DELETE CASCADE`). Anonymous history lives
  **only in the browser/device** (web `localStorage`, mobile `expo-secure-store`) and is
  never sent anywhere. Both are removable one by one or all at once.

### Abuse limits

`q` ≤ 100 chars (422 above), `limit` 1–20, Redis rate limit **60 searches/min and
120 tracking calls/min per client**. Rate limits key on the real visitor: the
server-rendered search page forwards `X-Forwarded-For`, which the API believes **only**
when the peer is inside `TRUSTED_PROXY_CIDRS` (otherwise the header is ignored, so it
can't be spoofed to dodge limits). Without that rule every server-rendered search would
share the web server's one bucket.

---

## 3. Engagement tracking and trending

### Write path (cheap, per request)

```
POST /engagement/view {entity_type, entity_id | slug}
  → entity must exist (and an article must be published)         ← no padding counters with made-up ids
  → SET NX EX 30m  seen:{signal}:{type}:{id}:{viewer}            ← refresh-spam protection
  → HINCRBY football:engagement:counts:{hour} "type:id:signal"   ← one Redis write
```

`viewer` is an HMAC (keyed with the server secret) of client IP + user agent, so it
cannot be reversed to an address and expires with the dedup window. The request path
never touches PostgreSQL counters. Search selections use the same pipeline with the
`search` signal (10-minute dedup). Redis being down means a view isn't counted — it
never errors.

### Aggregation (`aggregate_engagement`, Celery beat, every 60 s)

`SCAN` the hourly hashes → atomic `RENAME` to a private key (each batch is claimed by
exactly one run, concurrent traffic simply starts a new hash) → upsert
`engagement_buckets(entity_type, entity_id, signal, bucket, count)` with
`ON CONFLICT DO UPDATE count = count + excluded` and `articles.view_count += n` → delete
the claimed hash. On a database error the counts are put back in Redis. Orphaned claimed
batches from a crash are re-processed next run. Delivery is therefore **at-least-once**
(a crash between commit and delete can count one batch twice) — acceptable for popularity,
documented rather than hidden. Buckets older than 30 days are purged. The table holds
counts only: no user id, no IP.

### Trending (`calculate_trending`, every 5 min; `compute_trending`)

Transparent weights, no learning:

| signal | weight |
|---|---|
| page view (exponentially decayed, half-life 6 h) | 1 |
| chosen search result (decayed) | 3 |
| match view → each of its two teams (decayed) | 0.5 |
| team/competition has a **live match now** | +5 per match |
| new follows of the team/competition in the window | +2 each |
| articles published in the window linking the team/competition/category | +2 each |
| articles published in the window linking the player | +3 each |
| *articles:* views, then × a second decay on article age (half-life 48 h) | — |

Window default 24 h (`1…168` via `window_hours`). **An entity with no contribution is
not ranked at all** — there is no filler. Each entry returns `signals`
(`{views, searches, match_views, live_matches, follows, news}`) so a ranking can always
be explained; the UI turns that into words ("Playing live now", "Popular in the last 24
hours") and never presents it as football quality. Results are precomputed into Redis
(`football:trending:{type}:{window}h`, 15 min TTL); an API read that misses computes
once and caches (cache-aside).

---

## 4. Discovery home

`GET /discovery/home` (public, identical for everyone): latest finished results,
featured and latest articles, trending teams/players/articles, popular competitions
(trending competitions; before any engagement exists it falls back to the busiest
competitions by fixtures in the next 7 days — real activity, not an invented ranking).
Cached in Redis keyed by the article-cache version, so publishing refreshes it at once.

Live and upcoming matches stay exactly as they were (REST first paint, then the Phase 2
WebSocket). **The news/discovery feeds are deliberately not real-time**: ordinary
cached API calls. Web: the home page renders discovery sections under the live board
(each section absent if its data is empty; a discovery failure never affects the
scoreboard). Mobile: "For you" above and discovery sections below the match list.

---

## 5. Personalised feed

`GET /feed` (authenticated; **never** served to anyone but the caller). Cached under
`football:feed:user:{id}` for 45 s.

The ranking is a fixed list of tiers — the same list on every request, no model:

| rank | reason | what |
|---|---|---|
| 1 | `live_followed_match` | a live match you follow directly, or involving a followed team/competition |
| 2 | `followed_team_today` | a followed team (or followed match) plays today |
| 3 | `followed_competition_today` | a followed competition has a match today |
| 4 | `followed_team_upcoming` / `followed_competition_upcoming` | next 7 days (teams) / 3 days (competitions) |
| 5 | `recent_result` | finished in the last 3 days |
| 6 | `news_followed_team` / `news_followed_competition` | published in the last 7 days |
| 7 | `news_searched` | news about a team whose exact name you searched recently |
| 8 | `trending` | up to 3 trending articles |

Within a tier: live → most recently started first; fixtures → soonest; results and news
→ newest. A match appears once, in its best tier. **Every item carries an `explanation`**
("Liverpool is playing today", "News about Arsenal"). If the user follows nothing the feed
says `personalised: false` and returns trending/latest news instead. Recently-searched
teams use the user's own server-side search history; **per-user match view history is
deliberately not stored** (privacy), so "recently viewed" is not a feed signal.

Personalised news is the `news_*` tiers; anonymous users get the general news endpoints.

---

## 6. Caching summary

| Key | TTL | Invalidated by |
|---|---|---|
| `football:articles:{ver}:list:…`, `detail:{slug}`, `match:{id}:…`, `related:{slug}:…` | 120 s | any content mutation bumps `football:articles:ver` (old keys age out) |
| `football:discovery:home:{ver}` | 120 s | same version bump |
| `football:trending:{type}:{window}h` | 900 s | rewritten every 5 min by the beat task |
| `football:feed:user:{id}` | 45 s | TTL (a follow shows up within a minute) |
| `football:search:suggest:{prefix}` | 120 s | TTL |
| `football:search:popular:{day}` (zset) | 3 days | rolls by day |
| `football:engagement:counts:{hour}` | until aggregated (≤ 3 days) | consumed by the aggregator |

User-specific data is only ever keyed by user id and read for that user. Article
`view_count` in a response can lag the real count by up to the article cache TTL. Every
cache read fails open: a Redis outage degrades to database reads.

---

## 7. Notifications for articles

Reuses Phase 3's devices and senders (`NotificationService.send_payload_to_user`); does
**not** touch the match-event dispatcher. Deliberately conservative
(`content_notification_service.py`):

* **Opt-in** — five preferences (`team_news`, `competition_news`, `match_reports`,
  `transfer_news`, `general_news`), **all off** until the user turns them on
  (`GET/PUT /notifications/content-preferences`; web settings page and mobile settings
  screen).
* **Relevant** — team/competition kinds need the article linked to something the user
  follows; match reports need the *Match Reports* category plus a followed match/team/
  competition; transfer news needs the Transfers category or a "transfer" tag; general
  news is only sent for **featured** articles.
* **Capped** — at most 3 article pushes per user per UTC day.
* **Once** — `articles.notified_at` is claimed atomically and `(user, article)` is unique in
  `content_notification_log`, so republishing, a retried task or a duplicate enqueue never
  re-notifies.
* Only users with a registered device are reachable (the Phase 3 device registry is the
  "global" switch for push). Publishing enqueues the task and moves on; a dead broker
  never fails a publish.

The payload uses the same `{type, id}` deep-link contract: `{"type":"article","id":"<slug>"}`
opens `/article/<slug>` on web (service worker) and mobile (tap handler); both clients
allow-list the types and validate the id.

---

## 8. SEO, structured data and sharing

Every public page sets `generateMetadata`: title, description, **one canonical URL**
(`absoluteUrl` strips queries/fragments/trailing slashes), Open Graph (`article` type with
published/modified times for news) and a Twitter card (`summary_large_image` only when a
real http(s) image exists). `NEXT_PUBLIC_SITE_URL` is the canonical origin.

| Page | JSON-LD | Notes |
|---|---|---|
| `/article/{slug}` | `NewsArticle` (+ `about: SportsTeam[]`) | author/image/keywords omitted if absent |
| `/team/{id}` | `SportsTeam` | |
| `/competition/{id}` | `SportsOrganization` | |
| `/player/{id}` | `Person` (+ nationality, affiliation if known) | |
| `/match/{id}` | `SportsEvent` | `eventStatus` never claims *live*/*finished* (schema.org has none) |

JSON-LD is serialised with `<` escaped so a title can't close the script tag. Filtered/
paged `/news` variants are `noindex` with the canonical on `/news`; `/search`, account,
settings and editor pages are `noindex` and disallowed in `robots.txt`; `sitemap.xml` lists
the main pages, competitions and every published article. Not-found pages keep the
repository's existing behaviour (HTTP 200 + `noindex`, see README).

**Sharing**: web uses the native share sheet where present, else copies the link; mobile
uses the native share sheet. Both share only the canonical public URL built from the
entity's id/slug — never the current URL, so nothing about the sharer can leak. Deep links:
the web already answered on `/match|team|player|competition/{id}` (plural aliases redirect);
`/article/{slug}` is new. On mobile every screen is an Expo Router route
(`mobile://article/<slug>` etc.) and `+native-intent.tsx` maps the public site's URLs
(including plural aliases) to those screens, only for the five allowed types.

---

## 9. Testing

* **Backend** (`apps/api/tests`): `test_html_sanitizer.py` (29), `test_news_content.py`
  (workflow, auth, visibility, entities, related), `test_discovery_search.py` (grouping,
  ranking, abuse, suggestions, popular, recent), `test_discovery_engagement.py` (dedup,
  aggregation, trending, home, caches), `test_discovery_feed.py` (tiers, privacy, scoping),
  `test_content_notifications.py`, `test_client_ip.py`, and the continuous scenario
  `test_discovery_e2e.py` (register → follow → search → team page → publish → news/feed →
  article → related → view tracked → aggregated → trending → notification gated by
  preference → deep link → anonymous access).
* **Web** (`vitest`): `seo`, `search-history`, `news`, `editor` helpers.
* **Mobile** (`jest-expo` + RNTL): article card, entity news paging, content-notification
  settings, unified search screen, deep-link allow-list, news/search-history helpers.

## 10. Limitations

* No image/file upload — featured images are URLs (there is no storage subsystem).
* No scheduled publishing, no revision history, no rich-text editor (raw HTML + server
  sanitizer), and mobile cannot author.
* Trending is attention, not performance, and is only as good as the traffic: on a brand-new
  install the only signals are live matches and published news.
* `view_count` and trending lag by the aggregation/cache cadence (≈ 1–5 minutes).
* Aggregation is at-least-once (see §3).
* The sitemap lists articles, competitions and main pages, not every team/player/match.
* Search is lexical (trigram), not semantic and not accent-insensitive.
* Mobile universal/app links for an https domain need `associatedDomains`/`intentFilters`
  with a real domain; the routing side is in place, the domain configuration is not.
