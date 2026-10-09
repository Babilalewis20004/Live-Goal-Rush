"""Pure arithmetic behind analytics and predictions (Phase 6b). No database."""

import math

import pytest

from app.services.analytics_math import (
    MODEL_VERSION,
    UNIFORM_BRIER,
    LeagueBaseline,
    Result,
    TeamRecord,
    actual_outcome,
    brier_score,
    calibration_bins,
    outcome_probabilities,
    poisson_pmf,
    predict,
    safe_div,
    summarise_form,
)


def R(gf, ga):
    return Result(gf, ga)


# -- form -------------------------------------------------------------------------------------------


def test_form_summary_counts_and_streaks_from_most_recent_first():
    results = [R(2, 0), R(1, 0), R(0, 0), R(3, 1), R(0, 2)]  # newest first
    s = summarise_form(results, 5)
    assert (s.wins, s.draws, s.losses) == (3, 1, 1)
    assert (s.goals_for, s.goals_against, s.points) == (6, 3, 10)
    assert s.clean_sheets == 3 and s.failed_to_score == 2
    assert s.unbeaten_streak == 4  # W W D W, then the loss
    assert s.win_streak == 2
    assert s.scoring_streak == 2  # the 0-0 breaks it
    assert s.clean_sheet_streak == 3
    assert s.complete and s.limitation is None
    assert s.ppg == 2.0 and s.goals_for_per_match == 1.2


def test_form_summary_flags_an_incomplete_window_instead_of_pretending():
    s = summarise_form([R(1, 0), R(0, 1)], 5)
    assert not s.complete and s.played == 2
    assert s.limitation == "Only 2 of the last 5 matches are available."


def test_form_summary_with_no_matches_has_no_invented_averages():
    s = summarise_form([], 5)
    assert s.played == 0 and s.ppg is None and s.goals_for_per_match is None
    assert "No finished matches" in s.limitation


def test_safe_div_never_divides_by_zero_or_none():
    assert safe_div(3, 0) is None and safe_div(None, 4) is None and safe_div(7, 2) == 3.5


# -- the Poisson model --------------------------------------------------------------------------------


def test_poisson_pmf_is_a_distribution():
    assert math.isclose(sum(poisson_pmf(k, 1.7) for k in range(40)), 1.0, rel_tol=1e-9)


def test_outcome_probabilities_sum_to_one_and_favour_the_stronger_side():
    h, d, a = outcome_probabilities(2.2, 0.8)
    assert math.isclose(h + d + a, 1.0, rel_tol=1e-9)
    assert h > d > a


def test_equal_sides_are_symmetric():
    h, d, a = outcome_probabilities(1.3, 1.3)
    assert math.isclose(h, a, rel_tol=1e-9)


LEAGUE = LeagueBaseline(home_goals=1.5, away_goals=1.2, matches=200)


def record(home_for, home_against, away_for, away_against, n=5):
    return TeamRecord(home_for, home_against, n, away_for, away_against, n)


def test_prediction_is_reproducible_for_identical_input():
    home, away = record(10, 4, 8, 6), record(5, 9, 4, 10)
    assert predict(home, away, LEAGUE) == predict(home, away, LEAGUE)


def test_strong_home_side_against_a_weak_away_side_is_favoured_within_a_sane_range():
    strong = record(14, 3, 11, 4)   # scores plenty, concedes little
    weak = record(4, 10, 3, 12)
    p = predict(strong, weak, LEAGUE)
    assert p.outcome == "home"
    assert 0.55 < p.home_win < 0.95
    assert p.draw < 0.30 and p.away_win < 0.20
    assert math.isclose(p.home_win + p.draw + p.away_win, 1.0, abs_tol=2e-4)
    assert p.expected_home_goals > p.expected_away_goals
    assert math.isclose(p.expected_total_goals, p.expected_home_goals + p.expected_away_goals, abs_tol=0.02)


def test_average_teams_get_roughly_the_league_baseline():
    avg = record(round(1.5 * 10 / 2), round(1.2 * 10 / 2), 6, 7, n=5)  # about league-average both ways
    p = predict(avg, avg, LEAGUE)
    assert 0.35 < p.home_win < 0.55 and p.home_win > p.away_win  # home advantage comes from the league averages
    assert 2.0 < p.expected_total_goals < 3.4


def test_too_little_history_gives_no_prediction_rather_than_a_guess():
    assert predict(record(5, 2, 4, 3, n=1), record(3, 3, 3, 3, n=1), LEAGUE) is None
    assert predict(TeamRecord(), TeamRecord(), LEAGUE) is None


def test_shrinkage_keeps_small_samples_from_producing_extreme_estimates():
    lucky = TeamRecord(home_for=12, home_against=0, home_played=2, away_for=6, away_against=0, away_played=2)  # 4 matches, 18-0
    p = predict(lucky, record(5, 6, 5, 6), LEAGUE)
    assert p.expected_home_goals < 3.5 and p.home_win < 0.9
    assert p.confidence == "low"


def test_confidence_grows_with_the_sample_but_is_not_accuracy():
    small = predict(record(5, 5, 5, 5, n=2), record(5, 5, 5, 5, n=2), LEAGUE)
    big = predict(record(30, 30, 30, 30, n=15), record(30, 30, 30, 30, n=15), LEAGUE)
    assert (small.confidence, big.confidence) == ("low", "high")
    assert small.confidence_score < big.confidence_score <= 1.0


def test_model_version_is_stable_and_named():
    assert MODEL_VERSION == "poisson-v1"


# -- evaluation ---------------------------------------------------------------------------------------


def test_actual_outcome():
    assert [actual_outcome(2, 1), actual_outcome(1, 1), actual_outcome(0, 3)] == ["home", "draw", "away"]


def test_brier_score_perfect_worst_and_uniform():
    assert brier_score(1, 0, 0, "home") == 0
    assert brier_score(1, 0, 0, "away") == 2.0
    uniform = brier_score(1 / 3, 1 / 3, 1 / 3, "draw")
    assert math.isclose(uniform, UNIFORM_BRIER, abs_tol=1e-3) and math.isclose(UNIFORM_BRIER, 0.6667, abs_tol=1e-4)


def test_calibration_bins_compare_predicted_with_observed():
    pairs = [(0.1, False)] * 9 + [(0.1, True)] + [(0.9, True)] * 8 + [(0.9, False)] * 2
    bins = calibration_bins(pairs, bins=5)
    low, high = bins[0], bins[-1]
    assert (low.count, low.observed_rate, low.mean_predicted) == (10, 0.1, 0.1)
    assert (high.count, high.observed_rate) == (10, 0.8)
    assert all(b.count == 0 and b.observed_rate is None for b in bins[1:4])


@pytest.mark.parametrize("p", [0.0, 0.2, 0.999999, 1.0])
def test_probability_one_lands_in_the_last_bin(p):
    bins = calibration_bins([(p, True)], bins=5)
    assert sum(b.count for b in bins) == 1
