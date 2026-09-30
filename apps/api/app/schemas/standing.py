from pydantic import BaseModel, ConfigDict, computed_field

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
    season: str = ""
    group_name: str = ""
    description: str | None = None
    form: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against
