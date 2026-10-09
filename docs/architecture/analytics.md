# Analytics

Everything here is arithmetic over rows the platform already stores — finished matches, per-match team
statistics and per-match player statistics. Nothing is estimated, interpolated or filled in.

## Honesty rules

1. **Missing is not zero.** Every metric is a `Stat {value, sample}`. `value = null` means *no match in the
   window had it*; `sample` is how many matches contributed. Clients print `—` and "4 of 10 matches".
2. **Provider capability aware.** A statistic the provider never supplied is `null`. Metrics the schema cannot
   hold at all (`progressive_passes`, `expected_assists` for teams; `expected_goals`, `expected_assists`,
   `progressive_actions` for players) are listed in `unavailable` and never shown as numbers. Team xG is shown
   only where `match_statistics.expected_goals` was populated.
3. **Incomplete windows say so.** `limitations[]` ("Only 6 of the last 10 matches are stored", "Match
   statistics exist for 4 of 6 matches") and `FormSummary.complete = false`.
4. **Conversion uses matched pairs.** `shot_conversion_pct` = goals ÷ shots *only over matches where shots are
   known*, so a missing shot count cannot inflate it.

## Team analytics — `GET /api/v1/teams/{id}/analytics?scope=overall|home|away&window=5|10|20|38`

Window = the team's most recent *finished* matches in that scope. Sections:

| Section | Metrics |
|---|---|
| record | played, W/D/L, points, points per match |
| attack | goals, goals/match, shots, shots/match, shots on target, shot conversion, xG, xG/match, assists†, chances created† |
| possession | average possession, average pass accuracy, passes† |
| defence | goals conceded (+ per match), clean sheets, tackles†, interceptions†, clearances†, blocks† |
| discipline | yellow cards, red cards, fouls |

† summed from `player_match_statistics` for the team (only for matches that have player rows).

## Player analytics — `GET /api/v1/players/{id}/analytics?window=…`

Season history (appearances/goals/assists per competition and season); over the last *N* matches that have
statistics: totals, **per-90** figures (only when minutes are known), match-by-match lines and a goals+assists
trend.

## Form and head-to-head

* `FormSummary` (in `TeamFormOut.summary`): W/D/L, goals, clean sheets, points/match, **win / unbeaten /
  scoring / clean-sheet streaks**, `complete`, `limitation`. Free: last 5. Premium: `/teams/{id}/form/extended?limit=10`.
* `HeadToHeadOut` gained `window`, `total_meetings`, goals for each side, `average_goals`, `recent_form`
  (the match's home team's results, oldest → newest), `complete`, `limitation`. Free: last 5
  (`/matches/{id}/head-to-head`, unchanged URL). Premium: `/matches/{id}/head-to-head/extended?window=last10|all`
  (`all` = every stored meeting within 50 years).

## Match comparison — `GET /api/v1/matches/{id}/comparison`

Both teams' analytics *going into the match* (results strictly before kickoff, the match excluded), form
summaries, the last-5 H2H and a flat `rows[]` list. Each row says whether higher is better (`null` for
possession, which is style, not quality) so a UI can mark the leader — and `rowSummary` gives a spoken
sentence so colour and bars are never the only signal.

## Free vs Premium (enforced by the server)

| | Free | Premium |
|---|---|---|
| Team analytics | record, goals, goals/match, conceded, clean sheets (window ≤ 10) | all sections, windows 20/38 |
| Player analytics | season history | per-90, match-by-match, trend |
| Comparison | form (5), points/goals/clean sheets, H2H(5) | + possession, shots, xG, passing, tackles, discipline; form (10) |
| H2H / form | last 5 | last 10, all meetings |

The *shape* is decided after the cache: the full object is cached once and trimmed per request
(`AnalyticsService.shape_team/shape_player`; the comparison is cached per tier, not per user). A request that
asks for something only Premium has (a longer window) gets **402** with `{message, entitlement}`.

## Caching

| Key | TTL | Invalidated |
|---|---|---|
| `football:team:{id}:analytics:{scope}:{window}` | `ANALYTICS_CACHE_TTL_SECONDS` (900 s) | when one of the team's matches finishes (`worker/tasks._invalidate_after_finish`) |
| `football:player:{id}:analytics:{window}` | 900 s | TTL |
| `football:match:{id}:comparison:{basic|full}` | 900 s | TTL (pre-kickoff data only changes when earlier matches finish) |
| `football:team:{id}:form:{scope}:{10}` | `redis_default_ttl_seconds` | on match finish |

Entitlements themselves are **never cached**.

## Jobs

`calculate_team_analytics` (every 15 min) warms the cache for teams playing in the next 24 h. Requests never
trigger an expensive recomputation beyond one bounded SQL aggregate on a cache miss.

## Limits

* Statistics coverage is whatever the provider gave us; with the mock provider only some fields exist.
* "Chances created" is `key_passes`; there is no separate big-chance data.
* No opposition-adjusted metrics, no expected-assists, no tracking data.
