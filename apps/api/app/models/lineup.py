from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class MatchLineup(Base, TimestampMixin):
    """One team's announced lineup for one match. `formation` is only set
    when the provider supplies it -- never inferred from positions."""

    __tablename__ = "match_lineups"
    __table_args__ = (UniqueConstraint("match_id", "team_id", name="uq_match_lineups_match_team"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    formation: Mapped[str | None] = mapped_column(String(16), nullable=True)

    team: Mapped["Team"] = relationship()
    players: Mapped[list["LineupPlayer"]] = relationship(
        back_populates="lineup", cascade="all, delete-orphan", order_by="LineupPlayer.sort_order"
    )


class LineupPlayer(Base):
    __tablename__ = "lineup_players"
    __table_args__ = (UniqueConstraint("lineup_id", "player_id", name="uq_lineup_players_lineup_player"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lineup_id: Mapped[int] = mapped_column(
        ForeignKey("match_lineups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    is_starter: Mapped[bool] = mapped_column(nullable=False)
    position: Mapped[str | None] = mapped_column(String(50), nullable=True)
    shirt_number: Mapped[int | None] = mapped_column(nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    """Provider's ordering within the lineup (keeps the starting XI in
    formation order, e.g. goalkeeper first)."""

    lineup: Mapped[MatchLineup] = relationship(back_populates="players")
    player: Mapped["Player"] = relationship()
