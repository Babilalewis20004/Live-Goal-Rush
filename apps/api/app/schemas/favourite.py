from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.competition import CompetitionOut
from app.schemas.match import MatchSummary
from app.schemas.team import TeamOut


class FavouriteTeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    team: TeamOut


class FavouriteCompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    competition: CompetitionOut


class FavouriteMatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    match: MatchSummary


class FavouritesOut(BaseModel):
    """Aggregate shape for `GET /favourites`, mirroring `SearchResults`'
    multi-list-bundle convention (`schemas/search.py`)."""

    teams: list[FavouriteTeamOut]
    competitions: list[FavouriteCompetitionOut]
    matches: list[FavouriteMatchOut]
