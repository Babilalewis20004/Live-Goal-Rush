from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.form import FormSummaryOut, HeadToHeadOut
from app.schemas.team import TeamOut

Tier = Literal["basic", "full"]


class Stat(BaseModel):
    """One measured number. `value` is None when the provider did not supply
    it for any match in the window; `sample` is how many matches actually
    contributed, so a client can show "(3 of 10 matches)" instead of implying
    full coverage."""

    value: float | None = None
    sample: int = 0


class RecordOut(BaseModel):
    played: int
    wins: int
    draws: int
    losses: int
    points: int
    points_per_match: float | None = None


class TeamAnalyticsOut(BaseModel):
    team_id: int
    team_name: str
    scope: Literal["overall", "home", "away"]
    window: int
    matches_considered: int
    data_timestamp: datetime | None = None
    """Kickoff of the newest match included."""
    generated_at: datetime
    tier: Tier
    record: RecordOut
    attack: dict[str, Stat] = Field(default_factory=dict)
    possession: dict[str, Stat] = Field(default_factory=dict)
    defence: dict[str, Stat] = Field(default_factory=dict)
    discipline: dict[str, Stat] = Field(default_factory=dict)
    unavailable: list[str] = Field(default_factory=list)
    """Metrics this platform does not hold at all (never shown as zero)."""
    locked: list[str] = Field(default_factory=list)
    """Sections withheld from the caller's plan; empty for Premium."""
    limitations: list[str] = Field(default_factory=list)


class PlayerMatchLine(BaseModel):
    match_id: int
    kickoff_time: datetime
    opponent: str
    minutes: int | None = None
    goals: int | None = None
    assists: int | None = None
    shots: int | None = None
    shots_on_target: int | None = None
    key_passes: int | None = None
    tackles: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None


class PlayerSeasonLine(BaseModel):
    competition_id: int
    competition_name: str
    season: str
    appearances: int | None = None
    goals: int
    assists: int | None = None


class PlayerAnalyticsOut(BaseModel):
    player_id: int
    player_name: str
    generated_at: datetime
    tier: Tier
    seasons: list[PlayerSeasonLine] = Field(default_factory=list)
    """Historical season totals -- free."""
    window: int = 0
    matches_with_statistics: int = 0
    totals: dict[str, Stat] = Field(default_factory=dict)
    per_90: dict[str, Stat] = Field(default_factory=dict)
    recent: list[PlayerMatchLine] = Field(default_factory=list)
    form_goal_involvements: list[int] = Field(default_factory=list)
    """Goals + assists in each of the last matches, oldest to newest -- for a small trend chart."""
    unavailable: list[str] = Field(default_factory=list)
    locked: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ComparisonRow(BaseModel):
    key: str
    label: str
    home: float | None = None
    away: float | None = None
    higher_is_better: bool | None = True
    """None for neutral stats (possession) where "better" is a matter of style."""
    home_sample: int = 0
    away_sample: int = 0
    premium: bool = False


class MatchComparisonOut(BaseModel):
    match_id: int
    home_team: TeamOut
    away_team: TeamOut
    generated_at: datetime
    tier: Tier
    form_window: int
    home_form: FormSummaryOut | None = None
    away_form: FormSummaryOut | None = None
    home_sequence: str = ""
    away_sequence: str = ""
    head_to_head: HeadToHeadOut | None = None
    rows: list[ComparisonRow] = Field(default_factory=list)
    locked: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PredictionOut(BaseModel):
    match_id: int
    status: Literal["available", "insufficient_data", "unavailable"]
    label: str = "Model estimate"
    disclaimer: str = (
        "A statistical estimate from past results, not a guarantee and not betting advice."
    )
    model_version: str | None = None
    generated_at: datetime | None = None
    data_timestamp: datetime | None = None
    confidence: str | None = None
    confidence_score: float | None = None
    home_win: float | None = None
    draw: float | None = None
    away_win: float | None = None
    expected_total_goals: float | None = None
    expected_home_goals: float | None = None
    expected_away_goals: float | None = None
    influences: list[str] = Field(default_factory=list)
    """Plain-language list of the factors that fed the estimate."""
    factors: dict | None = None
    """Numeric inputs -- Premium only."""
    locked: list[str] = Field(default_factory=list)
    reason: str | None = None


class CalibrationBinOut(BaseModel):
    low: float
    high: float
    count: int
    mean_predicted: float | None = None
    observed_rate: float | None = None


class PredictionEvaluationSummary(BaseModel):
    model_version: str
    evaluated: int
    accuracy: float | None = None
    mean_brier_score: float | None = None
    baseline_brier_score: float
    """Brier score of always saying 1/3-1/3-1/3, the "no skill" reference."""
    beats_baseline: bool | None = None
    mean_total_goals_error: float | None = None
    calibration_home_win: list[CalibrationBinOut] = Field(default_factory=list)
    note: str


class InsightRecordOut(BaseModel):
    entity_type: str
    entity_id: int
    insight_type: str
    text: str
    value: float | None = None
    source_data_version: str
    generated_at: datetime
