from pydantic import BaseModel, Field

from app.schemas.article import ArticleSummary
from app.schemas.competition import CompetitionOut
from app.schemas.match import MatchSummary
from app.schemas.player import PlayerOut
from app.schemas.team import TeamOut


class SearchResults(BaseModel):
    """Grouped, relevance-ordered results (exact > prefix > contains >
    fuzzy within each group)."""

    teams: list[TeamOut] = Field(default_factory=list)
    competitions: list[CompetitionOut] = Field(default_factory=list)
    players: list[PlayerOut] = Field(default_factory=list)
    matches: list[MatchSummary] = Field(default_factory=list)
    articles: list[ArticleSummary] = Field(default_factory=list)
