# Front-end performance (web and mobile)

Measured with Lighthouse (mobile emulation, simulated throttling) against the production build served over plain HTTP from the compose stack on the 4-vCPU development VM, with the
browser, the API, PostgreSQL and the rest sharing that VM. **One run per page per state; absolute scores on a loaded VM are pessimistic and noisy — the before/after difference is the evidence, not the score.**
(Lighthouse's "Does not use HTTPS" audits are a consequence of testing over HTTP and are not a finding.)

## Baseline findings (before)

| Finding | Evidence |
|---|---|
| Team and league crests were served as the provider's originals (89–116 KB PNGs) and displayed at 26–64 px, because `images.unoptimized: true` was set globally | home page transferred 1,054 KB, mostly crests |
| `<Analytics />` (Vercel) was rendered on every production build; off Vercel `/_vercel/insights/script.js` is a 404 on every page | console error on every page; best-practices score 74 |
| The animated background animated `background-position` on a viewport-sized element and `scale()` on 120–140 px-blurred orbs | continuous main-thread repaint; TBT 4.8–9.3 s |

## Changes

* Crests go through Next's image optimizer (resized, WebP, cached 24 h) **only from an allow-list** of hosts (`NEXT_PUBLIC_CREST_IMAGE_HOSTS`, default `media.api-sports.io,crests.football-data.org`), so `/_next/image` is not an open proxy
  (a request for any other host returns 400 — verified). Unknown hosts, SVGs, article and editor images stay `unoptimized` (`lib/images.ts`, with tests).
* `<Analytics />` renders only when `VERCEL` is set.
* Background orbs animate `translate3d` only; the pitch lines translate by exactly one pattern period (160 px) instead of animating `background-position`; both are promoted with `will-change: transform`. The reduced-motion rule is unchanged.

## Result (same pages, same machine, same method)

| page | perf | LCP | TBT | transfer | best practices |
|---|---|---|---|---|---|
| home | 44 → **72** | 5.3 → 3.2 s | 9,330 → 940 ms | 1,054 → 278 KB | 74 → 96 |
| match/1081 | 50 → **69** | 4.9 → 3.5 s | 5,930 → 920 ms | 438 → 261 KB | 74 → 96 |
| article | 55 → **79** | 3.9 → 2.9 s | 4,770 → 650 ms | 200 → 200 KB | 74 → 96 |
| news | 47 → **82** | 5.2 → 2.9 s | 8,590 → 520 ms | 212 → 209 KB | 74 → 100 |

CLS is 0 on all pages before and after. The TBT drop cannot be attributed between the image and animation changes (they were measured together); the transfer drop is the images. Remaining: JS is 150–190 KB transferred per page
(39 chunks, 1,236 KB raw / 400 KB gzip in total; 59 of 110 components are client components) — a code-splitting pass is a Phase 8 candidate, not a launch blocker.

## Mobile review (no profiler run — code review and tests only)

* Crests use `expo-image` with disk caching (`components/team-badge.tsx`).
* The live board keeps a saved copy (`offline-cache.ts`, 24 h) and shows a stale banner when a refresh fails; the WebSocket is closed in the background and caught up on resume.
* The home screen renders lists in a `ScrollView` rather than a virtualised list; acceptable at current list sizes (tens of rows), to be revisited if they grow.
* Request timeouts are 15 s (60 s for export/delete).
