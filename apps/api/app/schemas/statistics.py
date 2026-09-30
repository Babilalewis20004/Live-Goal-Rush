from pydantic import BaseModel, ConfigDict, Field

from app.schemas.match import MatchSummary
from app.schemas.player import PlayerOut


class TeamMatchStatsOut(BaseModel):
    """`None` for a field = not supplied by the provider (never shown as 0)."""

    model_config = ConfigDict(from_attributes=True)

    team_id: int
    possession: float | None = None
    shots: int | None = None
    shots_on_target: int | None = None
    corners: int | None = None
    fouls: int | None = None
    offsides: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None
    pass_accuracy: float | None = None
    expected_goals: float | None = None


class MatchStatisticsOut(BaseModel):
    home: TeamMatchStatsOut | None = None
    away: TeamMatchStatsOut | None = None


class PlayerMatchStatsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    player: PlayerOut
    team_id: int
    minutes_played: int | None = None
    goals: int | None = None
    assists: int | None = None
    shots: int | None = None
    shots_on_target: int | None = None
    passes: int | None = None
    pass_accuracy: float | None = None
    key_passes: int | None = None
    tackles: int | None = None
    interceptions: int | None = None
    clearances: int | None = None
    blocks: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None
    fouls_committed: int | None = None


class MatchPlayerStatisticsOut(BaseModel):
    players: list[PlayerMatchStatsOut] = Field(default_factory=list)


class PlayerSeasonStatsOut(BaseModel):
    competition_id: int
    competition_name: str
    season: str
    team_id: int | None
    appearances: int | None
    goals: int
    assists: int | None
    penalties: int | None


class PlayerAppearanceOut(BaseModel):
    match: MatchSummary
    stats: PlayerMatchStatsOut


class PlayerStatisticsOut(BaseModel):
    seasons: list[PlayerSeasonStatsOut] = Field(default_factory=list)
    recent_matches: list[PlayerAppearanceOut] = Field(default_factory=list)


class TeamSeasonStatsOut(BaseModel):
    """One row per competition+season(+group) the team has a table entry in."""

    competition_id: int
    competition_name: str
    season: str
    group: str
    position: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int
    form: str | None


class TeamStatisticsOut(BaseModel):
    seasons: list[TeamSeasonStatsOut] = Field(default_factory=list)


class TeamRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    short_name: str | None
    logo_url: str | None


class TopScorerOut(BaseModel):
    rank: int
    player: PlayerOut
    team: TeamRef | None = None
    goals: int
    assists: int | None
    appearances: int | None
    penalties: int | None


class TopScorersOut(BaseModel):
    competition_id: int
    season: str | None
    scorers: list[TopScorerOut] = Field(default_factory=list)
