from pydantic import BaseModel, ConfigDict

from app.schemas.team import TeamOut


class StandingEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    team: TeamOut
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int
