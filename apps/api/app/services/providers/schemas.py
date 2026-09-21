"""Provider-side normalized DTOs.

These are the shapes every `FootballDataProvider` implementation (mock or
real) returns. They are intentionally provider-agnostic and independent of
both the external API's raw response format and our internal SQLAlchemy
models — the service layer is what maps these onto the database.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProviderCompetition(BaseModel):
    provider_id: str
    name: str
    country: str | None = None
    logo_url: str | None = None
    type: str = "league"


class ProviderTeam(BaseModel):
    provider_id: str
    name: str
    short_name: str | None = None
    country: str | None = None
    logo_url: str | None = None


class ProviderPlayer(BaseModel):
    provider_id: str
    name: str
    position: str | None = None
    photo_url: str | None = None


class ProviderMatchEvent(BaseModel):
    provider_id: str | None = None
    event_type: str
    minute: int
    extra_minute: int | None = None
    team: ProviderTeam | None = None
    player: ProviderPlayer | None = None
    assist_player: ProviderPlayer | None = None
    description: str | None = None


class ProviderMatch(BaseModel):
    provider_id: str
    competition: ProviderCompetition
    home_team: ProviderTeam
    away_team: ProviderTeam
    kickoff_time: datetime
    status: str
    home_score: int = 0
    away_score: int = 0
    half_time_home_score: int | None = None
    half_time_away_score: int | None = None
    venue: str | None = None
    minute: int | None = None
    events: list[ProviderMatchEvent] = Field(default_factory=list)


class ProviderStandingRow(BaseModel):
    team: ProviderTeam
    position: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int


class ProviderSearchResult(BaseModel):
    teams: list[ProviderTeam] = Field(default_factory=list)
    competitions: list[ProviderCompetition] = Field(default_factory=list)
    players: list[ProviderPlayer] = Field(default_factory=list)


__all__ = [
    "ProviderCompetition",
    "ProviderTeam",
    "ProviderPlayer",
    "ProviderMatchEvent",
    "ProviderMatch",
    "ProviderStandingRow",
    "ProviderSearchResult",
]
