from __future__ import annotations

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Standing(Base, TimestampMixin):
    """A team's row in a competition's table. Persisted (rather than only
    cached) so `GET /competitions/{id}/standings` can be served cache-aside
    from the database on a cache miss instead of calling the provider
    directly on every request (Phase 2 §5/§23) -- kept in sync by the
    worker's competition sync job."""

    __tablename__ = "standings"
    __table_args__ = (UniqueConstraint("competition_id", "team_id", name="uq_standings_competition_team"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(nullable=False)
    played: Mapped[int] = mapped_column(nullable=False)
    won: Mapped[int] = mapped_column(nullable=False)
    drawn: Mapped[int] = mapped_column(nullable=False)
    lost: Mapped[int] = mapped_column(nullable=False)
    goals_for: Mapped[int] = mapped_column(nullable=False)
    goals_against: Mapped[int] = mapped_column(nullable=False)
    points: Mapped[int] = mapped_column(nullable=False)

    competition: Mapped["Competition"] = relationship()
    team: Mapped["Team"] = relationship()
