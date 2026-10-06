from pydantic import BaseModel, ConfigDict


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    country: str | None
    logo_url: str | None
    type: str


class CompetitionSeasonsOut(BaseModel):
    current: str | None = None
    """The latest stored season (what the standings default to)."""
    seasons: list[str] = []
    """Every season with stored standings or scorers, newest first."""
    historical_supported: bool = False
    """Whether the provider can supply seasons that aren't stored yet; if so,
    asking for one queues a background sync and it appears shortly."""
