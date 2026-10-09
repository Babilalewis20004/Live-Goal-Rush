from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.competition import CompetitionOut
from app.schemas.team import TeamOut


class FormResultOut(BaseModel):
    match_id: int
    result: str  # "W" | "D" | "L"
    venue: str  # "home" | "away"
    opponent: TeamOut
    goals_for: int
    goals_against: int
    kickoff_time: datetime
    competition: CompetitionOut


class FormSummaryOut(BaseModel):
    """Counts and streaks over the same results. `complete` is False when fewer
    matches are stored than were asked for; `limitation` then says so."""

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
    ppg: float | None = None
    goals_for_per_match: float | None = None
    goals_against_per_match: float | None = None
    complete: bool
    limitation: str | None = None


class TeamFormOut(BaseModel):
    """Historical results only -- not a prediction. `results` is most recent
    first; `sequence` is the same results oldest-to-newest (how form is
    conventionally read, latest on the right)."""

    team_id: int
    scope: str  # "overall" | "home" | "away"
    limit: int
    results: list[FormResultOut] = Field(default_factory=list)
    sequence: str = ""
    summary: FormSummaryOut | None = None


class MatchFormOut(BaseModel):
    """Form of both teams going *into* this match (results before its
    kickoff only)."""

    home: TeamFormOut
    away: TeamFormOut


class HeadToHeadMeetingOut(BaseModel):
    match_id: int
    kickoff_time: datetime
    competition: CompetitionOut
    home_team: TeamOut
    away_team: TeamOut
    home_score: int
    away_score: int


class HeadToHeadOut(BaseModel):
    """Finished meetings of the two teams before `before`, in any
    competition we hold results for, within `period_start`..`before`,
    capped at the `limit` most recent. The window is explicit because
    "all time" would silently mean "whatever we happen to have stored".
    Wins are counted relative to the *match's* home/away teams, whichever
    side each played in the past meeting."""

    home_team_id: int
    away_team_id: int
    limit: int | None
    """None = every stored meeting inside the lookback."""
    window: str = "last5"  # "last5" | "last10" | "all"
    period_start: datetime
    before: datetime
    meetings: list[HeadToHeadMeetingOut] = Field(default_factory=list)
    home_team_wins: int = 0
    draws: int = 0
    away_team_wins: int = 0
    total_meetings: int = 0
    home_team_goals: int = 0
    away_team_goals: int = 0
    average_goals: float | None = None
    recent_form: str = ""
    """The match's home team's results in these meetings, oldest to newest (W/D/L)."""
    complete: bool = True
    limitation: str | None = None
