from __future__ import annotations

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class FavouriteTeam(Base, TimestampMixin):
    """A user following a team (Phase 3 §8). `ondelete="CASCADE"` on both
    sides means a deleted user or a deleted team silently drops the
    favourite row -- this app never actually deletes teams today, but the
    constraint is still correct and worth having."""

    __tablename__ = "favourite_teams"
    __table_args__ = (
        UniqueConstraint("user_id", "team_id", name="uq_favourite_teams_user_team"),
        # "Which teams gained followers in the last day?" (trending) filters on a short time window.
        Index("ix_favourite_teams_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )

    team: Mapped["Team"] = relationship()  # noqa: F821


class FavouriteCompetition(Base, TimestampMixin):
    """A user following a competition (Phase 3 §9)."""

    __tablename__ = "favourite_competitions"
    __table_args__ = (
        UniqueConstraint("user_id", "competition_id", name="uq_favourite_competitions_user_competition"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    competition: Mapped["Competition"] = relationship()  # noqa: F821


class FavouriteMatch(Base, TimestampMixin):
    """A user following an individual match (Phase 3 §10)."""

    __tablename__ = "favourite_matches"
    __table_args__ = (UniqueConstraint("user_id", "match_id", name="uq_favourite_matches_user_match"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )

    match: Mapped["Match"] = relationship()  # noqa: F821
