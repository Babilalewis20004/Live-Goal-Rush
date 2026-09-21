from pydantic import BaseModel, ConfigDict


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    country: str | None
    logo_url: str | None
    type: str
