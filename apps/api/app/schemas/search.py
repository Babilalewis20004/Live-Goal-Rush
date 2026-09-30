from pydantic import BaseModel, Field

from app.schemas.competition import CompetitionOut
from app.schemas.match import MatchSummary
from app.schemas.player import PlayerOut
from app.schemas.team import TeamOut


class SearchResults(BaseModel):
    teams: list[TeamOut] = Field(default_factory=list)
    competitions: list[CompetitionOut] = Field(default_factory=list)
    players: list[PlayerOut] = Field(default_factory=list)
    matches: list[MatchSummary] = Field(default_factory=list)
