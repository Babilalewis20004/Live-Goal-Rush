from __future__ import annotations

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import MatchEventType
from app.models.mixins import TimestampMixin


class MatchEvent(Base, TimestampMixin):
    __tablename__ = "match_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[MatchEventType] = mapped_column(
        Enum(MatchEventType, native_enum=False, validate_strings=True, length=32), nullable=False
    )
    minute: Mapped[int] = mapped_column(nullable=False)
    extra_minute: Mapped[int | None] = mapped_column(nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True, index=True)
    assist_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)

    match: Mapped["Match"] = relationship(back_populates="events")
    team: Mapped["Team | None"] = relationship(foreign_keys=[team_id])
    player: Mapped["Player | None"] = relationship(foreign_keys=[player_id])
    assist_player: Mapped["Player | None"] = relationship(foreign_keys=[assist_player_id])
