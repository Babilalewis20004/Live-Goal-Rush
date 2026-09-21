from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.competition import CompetitionOut
from app.schemas.player import PlayerOut
from app.schemas.team import TeamOut


class MatchSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    competition: CompetitionOut
    home_team: TeamOut
    away_team: TeamOut
    kickoff_time: datetime
    status: str
    home_score: int
    away_score: int
    half_time_home_score: int | None
    half_time_away_score: int | None
    minute: int | None
    venue: str | None


class MatchEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    minute: int
    extra_minute: int | None
    team: TeamOut | None
    player: PlayerOut | None
    assist_player: PlayerOut | None
    description: str | None


class MatchDetail(MatchSummary):
    events: list[MatchEventOut] = Field(default_factory=list)
