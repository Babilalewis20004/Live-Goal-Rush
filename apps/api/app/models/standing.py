from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Standing(Base, TimestampMixin):
    """A team's row in a competition's table for one season (and, for group
    stages, one group). Persisted (rather than only cached) so
    `GET /competitions/{id}/standings` can be served cache-aside from the
    database on a cache miss instead of calling the provider directly on
    every request (Phase 2 §5/§23) -- kept in sync by the worker's
    competition sync job and, as of Phase 4, re-synced when a match in the
    competition finishes."""

    __tablename__ = "standings"
    __table_args__ = (
        UniqueConstraint(
            "competition_id",
            "season",
            "group_name",
            "team_id",
            name="uq_standings_competition_season_group_team",
        ),
        Index("ix_standings_competition_season", "competition_id", "season"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    season: Mapped[str] = mapped_column(String(16), nullable=False)
    """Season label, e.g. "2026/27" -- see `app/services/season.py`."""
    group_name: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    """Group/stage label for group-stage competitions; "" for a single
    table (kept non-null so the unique constraint above actually
    deduplicates -- NULLs are distinct in a Postgres unique index)."""
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(nullable=False)
    played: Mapped[int] = mapped_column(nullable=False)
    won: Mapped[int] = mapped_column(nullable=False)
    drawn: Mapped[int] = mapped_column(nullable=False)
    lost: Mapped[int] = mapped_column(nullable=False)
    goals_for: Mapped[int] = mapped_column(nullable=False)
    goals_against: Mapped[int] = mapped_column(nullable=False)
    points: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """Provider-supplied classification of this position (promotion,
    relegation, qualification, playoff...). Never hard-coded by us --
    competition rules differ."""
    form: Mapped[str | None] = mapped_column(String(16), nullable=True)
    """Provider-supplied recent-form string (e.g. "WWDLW"), when given."""

    competition: Mapped["Competition"] = relationship()
    team: Mapped["Team"] = relationship()
