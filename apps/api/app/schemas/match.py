from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.config import settings
from app.schemas.common import DataStatus
from app.schemas.competition import CompetitionOut
from app.schemas.player import PlayerOut
from app.schemas.team import TeamOut

_LIVE_STATUSES = ("live", "halftime")


class MatchSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    competition: CompetitionOut
    home_team: TeamOut
    away_team: TeamOut
    kickoff_time: datetime
    status: str
    home_score: int
    away_score: int
    half_time_home_score: int | None
    half_time_away_score: int | None
    minute: int | None
    venue: str | None
    last_synced_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def data_status(self) -> DataStatus:
        """Stale-data detection (Phase 2 §21). Computed at serialization
        time (not stored), so it reflects freshness as of *this response*
        even when `self` came from a Redis cache entry that's been sitting
        for a few seconds -- age is measured against "now", not against
        when the cache entry was written."""
        if self.last_synced_at is None:
            return DataStatus.UNAVAILABLE
        is_live = self.status in _LIVE_STATUSES
        threshold = (
            settings.live_poll_interval_seconds * 3
            if is_live
            else settings.redis_default_ttl_seconds * 2
        )
        age_seconds = (datetime.now(timezone.utc) - self.last_synced_at).total_seconds()
        return DataStatus.FRESH if age_seconds <= threshold else DataStatus.STALE


class MatchEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    minute: int
    extra_minute: int | None
    team: TeamOut | None
    player: PlayerOut | None
    assist_player: PlayerOut | None
    description: str | None


class MatchDetail(MatchSummary):
    events: list[MatchEventOut] = Field(default_factory=list)
