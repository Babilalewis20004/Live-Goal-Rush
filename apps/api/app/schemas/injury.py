from datetime import datetime

from pydantic import BaseModel


class InjuryOut(BaseModel):
    player_name: str
    photo_url: str | None = None
    kind: str
    """"missing" or "doubtful"."""
    reason: str | None = None
    match_date: datetime | None = None


class TeamInjuriesOut(BaseModel):
    supported: bool
    """False when the active data provider has no injury feed."""
    items: list[InjuryOut]
