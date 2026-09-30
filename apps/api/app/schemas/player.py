from pydantic import BaseModel, ConfigDict

from app.schemas.team import TeamOut


class PlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    position: str | None
    photo_url: str | None
    nationality: str | None = None
    shirt_number: int | None = None


class PlayerDetail(PlayerOut):
    team: TeamOut | None = None
