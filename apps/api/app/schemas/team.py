from pydantic import BaseModel, ConfigDict, Field

from app.schemas.competition import CompetitionOut


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    short_name: str | None
    country: str | None
    logo_url: str | None


class TeamDetail(TeamOut):
    venue: str | None = None
    competitions: list[CompetitionOut] = Field(default_factory=list)
    """Competitions this team currently appears in a table for."""
