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
    venue: str | None = None


class ProviderPlayer(BaseModel):
    provider_id: str
    name: str
    position: str | None = None
    photo_url: str | None = None
    nationality: str | None = None
    shirt_number: int | None = None
    team: ProviderTeam | None = None
    """Current team, when the call that produced this player knows it
    (squad / profile calls do; match-event players carry it on the event)."""


class ProviderMatchEvent(BaseModel):
    provider_id: str | None = None
    event_type: str
    minute: int
    extra_minute: int | None = None
    team: ProviderTeam | None = None
    player: ProviderPlayer | None = None
    assist_player: ProviderPlayer | None = None
    description: str | None = None
    event_detail: str | None = None


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
    season: str | None = None
    """Season label; `None` means "the provider didn't say" and the service
    falls back to `season.current_season_label()`."""
    group: str | None = None
    description: str | None = None
    form: str | None = None
    position: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int


class ProviderLineupPlayer(BaseModel):
    player: ProviderPlayer
    is_starter: bool
    position: str | None = None
    shirt_number: int | None = None


class ProviderLineup(BaseModel):
    team: ProviderTeam
    formation: str | None = None
    """Only set when the provider states a formation -- never inferred."""
    players: list[ProviderLineupPlayer] = Field(default_factory=list)


class ProviderTeamMatchStatistics(BaseModel):
    """Every field is optional: `None` = not supplied, which is not 0."""

    team: ProviderTeam
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


class ProviderPlayerMatchStatistics(BaseModel):
    player: ProviderPlayer
    team: ProviderTeam
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


class ProviderTopScorer(BaseModel):
    player: ProviderPlayer
    team: ProviderTeam | None = None
    season: str | None = None
    goals: int
    assists: int | None = None
    appearances: int | None = None
    penalties: int | None = None


class ProviderCapabilities(BaseModel):
    """What the active provider can actually supply (Phase 4 §27). Checked
    by the sync layer before calling an optional method, and exposed at
    `GET /api/v1/capabilities` so clients can render an honest
    "not available from this data provider" state instead of an empty
    section that looks like a bug. Head-to-head and form are *derived* from
    stored match results, so they aren't provider capabilities."""

    match_events: bool = False
    lineups: bool = False
    match_statistics: bool = False
    player_statistics: bool = False
    team_squads: bool = False
    player_profiles: bool = False
    standings: bool = True
    top_scorers: bool = False
    venues: bool = False
    historical_seasons: bool = False
    """Can supply standings / top scorers for *past* seasons on request."""


class ProviderInjury(BaseModel):
    player: ProviderPlayer
    team: ProviderTeam | None = None
    kind: str
    """"missing" (ruled out) or "doubtful" (questionable)."""
    reason: str | None = None
    match_date: datetime | None = None
    """Kickoff of the fixture the absence applies to."""


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
    "ProviderLineupPlayer",
    "ProviderLineup",
    "ProviderTeamMatchStatistics",
    "ProviderPlayerMatchStatistics",
    "ProviderTopScorer",
    "ProviderInjury",
    "ProviderCapabilities",
    "ProviderSearchResult",
]
