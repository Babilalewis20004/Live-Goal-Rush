"""Pure football arithmetic for Phase 6 analytics and predictions.

No database, no Redis, no clock: every function is a deterministic function of
its arguments, so the same stored results always give the same numbers. That is
what makes predictions reproducible and testable with fixed fixtures.

Nothing here invents data. A ratio whose denominator is zero (or unknown) is
`None`, never 0 -- the UI says "not available" instead of showing a fake value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

# --------------------------------------------------------------------------------------------
# Form
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    """One finished match from a single team's point of view."""

    goals_for: int
    goals_against: int

    @property
    def letter(self) -> str:
        return "W" if self.goals_for > self.goals_against else "D" if self.goals_for == self.goals_against else "L"


@dataclass(frozen=True)
class FormSummary:
    played: int
    requested: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    clean_sheets: int
    failed_to_score: int
    points: int
    scoring_streak: int
    unbeaten_streak: int
    win_streak: int
    clean_sheet_streak: int
    complete: bool
    limitation: str | None = None
    ppg: float | None = None
    goals_for_per_match: float | None = None
    goals_against_per_match: float | None = None


def safe_div(numerator: float | int | None, denominator: float | int | None, digits: int = 2) -> float | None:
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, digits)


def _streak(results: Sequence[Result], predicate) -> int:
    n = 0
    for r in results:  # most recent first
        if not predicate(r):
            break
        n += 1
    return n


def summarise_form(results: Sequence[Result], requested: int) -> FormSummary:
    """Summarise `results` (most recent first). `complete` is False when fewer
    matches exist than were asked for -- the summary is then labelled with the
    limitation rather than silently presented as a full window."""
    n = len(results)
    wins = sum(r.letter == "W" for r in results)
    draws = sum(r.letter == "D" for r in results)
    losses = n - wins - draws
    gf = sum(r.goals_for for r in results)
    ga = sum(r.goals_against for r in results)
    complete = n >= requested
    limitation = None
    if n == 0:
        limitation = "No finished matches are stored for this selection."
    elif not complete:
        limitation = f"Only {n} of the last {requested} matches are available."
    return FormSummary(
        played=n,
        requested=requested,
        wins=wins,
        draws=draws,
        losses=losses,
        goals_for=gf,
        goals_against=ga,
        clean_sheets=sum(r.goals_against == 0 for r in results),
        failed_to_score=sum(r.goals_for == 0 for r in results),
        points=wins * 3 + draws,
        scoring_streak=_streak(results, lambda r: r.goals_for > 0),
        unbeaten_streak=_streak(results, lambda r: r.letter != "L"),
        win_streak=_streak(results, lambda r: r.letter == "W"),
        clean_sheet_streak=_streak(results, lambda r: r.goals_against == 0),
        complete=complete,
        limitation=limitation,
        ppg=safe_div(wins * 3 + draws, n),
        goals_for_per_match=safe_div(gf, n),
        goals_against_per_match=safe_div(ga, n),
    )


# --------------------------------------------------------------------------------------------
# Poisson match model
# --------------------------------------------------------------------------------------------

MODEL_VERSION = "poisson-v1"
MIN_MATCHES_PER_TEAM = 3
SHRINKAGE_MATCHES = 5.0
"""Pseudo-matches of league-average performance blended into each team's
record. With few real matches the team is pulled towards the league average
(sensible), with many it is barely moved (data dominates)."""
MAX_GOALS = 10
DEFAULT_HOME_GOALS = 1.5
DEFAULT_AWAY_GOALS = 1.2


@dataclass(frozen=True)
class TeamRecord:
    """A team's scoring record over its recent matches, split by venue."""

    home_for: int = 0
    home_against: int = 0
    home_played: int = 0
    away_for: int = 0
    away_against: int = 0
    away_played: int = 0

    @property
    def played(self) -> int:
        return self.home_played + self.away_played


@dataclass(frozen=True)
class LeagueBaseline:
    """Average goals per match for the home and the away side."""

    home_goals: float = DEFAULT_HOME_GOALS
    away_goals: float = DEFAULT_AWAY_GOALS
    matches: int = 0


@dataclass(frozen=True)
class Prediction:
    home_win: float
    draw: float
    away_win: float
    expected_home_goals: float
    expected_away_goals: float
    expected_total_goals: float
    confidence_score: float
    confidence: str
    factors: dict = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        return max((("home", self.home_win), ("draw", self.draw), ("away", self.away_win)), key=lambda p: p[1])[0]


def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def score_matrix(lam_home: float, lam_away: float, max_goals: int = MAX_GOALS) -> list[list[float]]:
    return [[poisson_pmf(h, lam_home) * poisson_pmf(a, lam_away) for a in range(max_goals + 1)] for h in range(max_goals + 1)]


def outcome_probabilities(lam_home: float, lam_away: float) -> tuple[float, float, float]:
    """(home, draw, away), renormalised so the truncated tail cannot leak mass."""
    m = score_matrix(lam_home, lam_away)
    home = sum(m[h][a] for h in range(len(m)) for a in range(len(m)) if h > a)
    draw = sum(m[h][h] for h in range(len(m)))
    away = sum(m[h][a] for h in range(len(m)) for a in range(len(m)) if h < a)
    total = home + draw + away
    return home / total, draw / total, away / total


def _strength(goals: float, played: int, baseline: float, prior: float = SHRINKAGE_MATCHES) -> float:
    """Shrunk goals-per-match as a multiple of the league baseline."""
    if baseline <= 0:
        return 1.0
    return (goals + prior * baseline) / ((played + prior) * baseline)


def confidence_for(sample: int) -> tuple[float, str]:
    """A transparent function of how much history there is -- not a claim about
    accuracy (that is measured separately, by prediction evaluation)."""
    score = round(min(1.0, sample / 20), 2)
    label = "low" if sample < 6 else "medium" if sample < 12 else "high"
    return score, label


def predict(home: TeamRecord, away: TeamRecord, league: LeagueBaseline) -> Prediction | None:
    """Independent-Poisson estimate. Returns None when either team has fewer
    than MIN_MATCHES_PER_TEAM stored results: better no estimate than a made-up one.

    expected home goals = league home average x home attack x away defence weakness
    expected away goals = league away average x away attack x home defence weakness
    where each team's strengths use its own home/away record shrunk to the league mean.
    """
    if home.played < MIN_MATCHES_PER_TEAM or away.played < MIN_MATCHES_PER_TEAM:
        return None
    lh, la = league.home_goals, league.away_goals
    home_attack = _strength(home.home_for, home.home_played, lh)
    home_defence = _strength(home.home_against, home.home_played, la)  # >1 = concedes more
    away_attack = _strength(away.away_for, away.away_played, la)
    away_defence = _strength(away.away_against, away.away_played, lh)
    lam_h = lh * home_attack * away_defence
    lam_a = la * away_attack * home_defence
    # Keep the Poisson means in a sane football range.
    lam_h = min(max(lam_h, 0.2), 5.0)
    lam_a = min(max(lam_a, 0.2), 5.0)
    p_h, p_d, p_a = outcome_probabilities(lam_h, lam_a)
    sample = min(home.played, away.played)
    score, label = confidence_for(sample)
    return Prediction(
        home_win=round(p_h, 4),
        draw=round(p_d, 4),
        away_win=round(p_a, 4),
        expected_home_goals=round(lam_h, 2),
        expected_away_goals=round(lam_a, 2),
        expected_total_goals=round(lam_h + lam_a, 2),
        confidence_score=score,
        confidence=label,
        factors={
            "home_attack": round(home_attack, 3),
            "home_defence": round(home_defence, 3),
            "away_attack": round(away_attack, 3),
            "away_defence": round(away_defence, 3),
            "league_home_goals": round(lh, 3),
            "league_away_goals": round(la, 3),
            "home_matches": home.played,
            "away_matches": away.played,
            "league_matches": league.matches,
        },
    )


# --------------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------------


def actual_outcome(home_goals: int, away_goals: int) -> str:
    return "home" if home_goals > away_goals else "draw" if home_goals == away_goals else "away"


def brier_score(p_home: float, p_draw: float, p_away: float, outcome: str) -> float:
    """Multi-class Brier score: 0 is perfect; always guessing 1/3 scores 0.667."""
    return round(
        (p_home - (outcome == "home")) ** 2 + (p_draw - (outcome == "draw")) ** 2 + (p_away - (outcome == "away")) ** 2,
        4,
    )


UNIFORM_BRIER = round(2 * (1 / 3) ** 2 + (2 / 3) ** 2, 4)  # 0.6667: the "no skill" reference


@dataclass(frozen=True)
class CalibrationBin:
    low: float
    high: float
    count: int
    mean_predicted: float | None
    observed_rate: float | None


def calibration_bins(pairs: Iterable[tuple[float, bool]], bins: int = 5) -> list[CalibrationBin]:
    """Reliability table for one outcome: predicted probability vs how often it happened."""
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for p, hit in pairs:
        buckets[min(int(p * bins), bins - 1)].append((p, hit))
    out = []
    for i, items in enumerate(buckets):
        out.append(
            CalibrationBin(
                low=round(i / bins, 2),
                high=round((i + 1) / bins, 2),
                count=len(items),
                mean_predicted=round(sum(p for p, _ in items) / len(items), 3) if items else None,
                observed_rate=round(sum(h for _, h in items) / len(items), 3) if items else None,
            )
        )
    return out
