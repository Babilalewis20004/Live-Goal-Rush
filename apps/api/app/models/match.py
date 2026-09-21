from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import MatchStatus
from app.models.mixins import TimestampMixin


class Match(Base, TimestampMixin):
    __tablename__ = "matches"
    __table_args__ = (
        Index("ix_matches_competition_kickoff", "competition_id", "kickoff_time"),
        Index("ix_matches_status_kickoff", "status", "kickoff_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    kickoff_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, native_enum=False, validate_strings=True, length=32),
        default=MatchStatus.SCHEDULED,
        nullable=False,
        index=True,
    )
    home_score: Mapped[int] = mapped_column(default=0, nullable=False)
    away_score: Mapped[int] = mapped_column(default=0, nullable=False)
    half_time_home_score: Mapped[int | None] = mapped_column(nullable=True)
    half_time_away_score: Mapped[int | None] = mapped_column(nullable=True)
    venue: Mapped[str | None] = mapped_column(String(255), nullable=True)
    minute: Mapped[int | None] = mapped_column(nullable=True)
    """Current live minute. Not in the spec's minimum field list but needed to
    render an in-progress match without recomputing elapsed time client-side."""
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When this row was last written from a provider sync (worker task or
    startup seed). Used to compute `data_status` (FRESH/STALE/UNAVAILABLE)
    for stale-data detection (Phase 2 §21) -- distinct from `updated_at`,
    which also changes for non-provider writes."""

    competition: Mapped["Competition"] = relationship(back_populates="matches")
    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])
    events: Mapped[list["MatchEvent"]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="MatchEvent.minute"
    )
