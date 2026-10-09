# Predictions

> **Statistical estimates, not advice.** There is no betting, bookmaker, odds or gambling functionality
> anywhere in the product, and the UI never presents an estimate as a fact or a recommendation.

## The model — `poisson-v1` (`services/analytics_math.py`)

Deterministic, no randomness, no machine learning. For a match between *H* (home) and *A* (away):

1. Gather each team's goals scored and conceded over its last `ANALYTICS_WINDOW_MATCHES` (20) finished matches
   *before kickoff*, split by venue.
2. League baselines: average home goals and away goals per match in the competition (the last 300 finished
   matches; if the competition has fewer than 10, all stored finished matches; if there are still fewer than
   10, fixed defaults of 1.5 / 1.2).
3. Strengths, each *shrunk towards 1.0* by five pseudo-matches so a hot streak over a few games cannot produce
   an extreme estimate:
   `strength = (goals + 5·baseline) / ((matches + 5)·baseline)`.
4. Expected goals: `λ_home = league_home × H.attack(home) × A.defence_weakness(away)`,
   `λ_away = league_away × A.attack(away) × H.defence_weakness(home)`, clamped to 0.2–5.0.
5. Independent Poisson scores 0–10 each → probabilities of home win / draw / away win (renormalised so the
   truncated tail cannot leak probability) and expected total goals.

Home advantage is not a tuned constant: it comes from the league's own home/away scoring averages.

**Refusal instead of guessing:** with fewer than 3 finished matches for either team there is no estimate
(`status: "insufficient_data"`).

**Confidence** (`low` < 6 matches, `medium` < 12, else `high`; score = min(1, n/20)) is a function of *sample
size only*. It is not a claim about accuracy.

## What is stored (`predictions`)

`match_id`, `model_version`, the three probabilities, expected home/away/total goals, `confidence`,
`confidence_score`, `factors` (the numeric inputs), **`data_timestamp`** (kickoff of the newest match used),
**`generated_at`**. One row per `(match_id, model_version)`; regenerating with the same data produces the same
numbers (tested). A match that has kicked off is **never regenerated or created** — the stored row stays as
it was, so evaluation judges a genuine pre-match estimate.

## How it is produced

`generate_predictions` (Celery beat, every 30 min) estimates every `SCHEDULED` match kicking off within
`PREDICTION_HORIZON_HOURS` (72). API requests only read; they never compute. A newly created estimate
publishes `prediction.updated` on the match's WebSocket and may trigger an opt-in "Match estimate available"
notification to followers.

## Evaluation (`prediction_evaluations`) — `GET /api/v1/predictions/evaluation`

`evaluate_predictions` (every 15 min) scores each stored prediction once its match is finished (unique
`prediction_id` ⇒ idempotent): predicted outcome, actual outcome, correct?, **multi-class Brier score**, and
the total-goals error. The summary endpoint reports:

* `evaluated` — the sample size (always shown),
* `accuracy` (share of matches where the top-probability outcome happened),
* `mean_brier_score` against `baseline_brier_score` = 0.6667 (always guessing ⅓-⅓-⅓) and `beats_baseline`,
* a **calibration table** for the home-win probability (predicted vs observed rate by 0.2 bin),
* a plain-language `note`.

With no evaluated predictions every figure is `null` and the note says "no accuracy is claimed". **No accuracy
claim is made anywhere without that measured evidence**, and a small sample is flagged as such.

## What the UI shows

"Model estimate" / "Statistical prediction", three whole-number percentages that always sum to 100 (largest
remainder), expected total goals, a confidence line, **"Prediction influenced by"** (only factors the model
really uses — recent results, goals for/against vs the league, league scoring averages, home advantage; it
does *not* claim head-to-head, injuries or lineups), the disclaimer, model version and age. Premium adds the
per-team expected goals and the model inputs.

## Limits

* Independent Poisson ignores correlation between teams' goals (draws are under-estimated for low-scoring
  teams), injuries, suspensions, lineups, rest days and opposition quality beyond goals.
* Early in a season, or in a competition with little stored history, the league baseline falls back to defaults.
* Predictions cover match results and goals only; there are no player or team-trajectory predictions (the data
  to support them honestly is not stored).
* It has not been compared with any other model. Recommended Phase 7 work: accumulate evaluations, then try
  Elo / Dixon-Coles variants *under a new `model_version`* and compare Brier scores on the same matches.
