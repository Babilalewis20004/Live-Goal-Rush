from pydantic import BaseModel, Field

from app.schemas.player import PlayerOut
from app.schemas.team import TeamOut


class LineupPlayerOut(BaseModel):
    player: PlayerOut
    position: str | None
    shirt_number: int | None
    is_starter: bool
    subbed_in_minute: int | None = None
    subbed_out_minute: int | None = None
    """Derived from the match's substitution events (player = on,
    assist_player = off), so the lineup and the timeline can't disagree."""


class TeamLineupOut(BaseModel):
    team: TeamOut
    formation: str | None
    starters: list[LineupPlayerOut] = Field(default_factory=list)
    substitutes: list[LineupPlayerOut] = Field(default_factory=list)


class MatchLineupsOut(BaseModel):
    """Both `None` = the provider hasn't supplied lineups (yet, or ever --
    `GET /capabilities` says which)."""

    home: TeamLineupOut | None = None
    away: TeamLineupOut | None = None
