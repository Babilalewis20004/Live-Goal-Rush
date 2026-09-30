"""Statistics tables (Phase 4). Every numeric column is nullable on purpose:
NULL means "the provider did not supply this", which is different from 0 and
must never be displayed as 0."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class MatchStatistic(Base, TimestampMixin):
    __tablename__ = "match_statistics"
    __table_args__ = (UniqueConstraint("match_id", "team_id", name="uq_match_statistics_match_team"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    possession: Mapped[float | None] = mapped_column(Float, nullable=True)
    shots: Mapped[int | None] = mapped_column(nullable=True)
    shots_on_target: Mapped[int | None] = mapped_column(nullable=True)
    corners: Mapped[int | None] = mapped_column(nullable=True)
    fouls: Mapped[int | None] = mapped_column(nullable=True)
    offsides: Mapped[int | None] = mapped_column(nullable=True)
    yellow_cards: Mapped[int | None] = mapped_column(nullable=True)
    red_cards: Mapped[int | None] = mapped_column(nullable=True)
    pass_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_goals: Mapped[float | None] = mapped_column(Float, nullable=True)


class PlayerMatchStatistic(Base, TimestampMixin):
    __tablename__ = "player_match_statistics"
    __table_args__ = (
        UniqueConstraint("match_id", "player_id", name="uq_player_match_statistics_match_player"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    minutes_played: Mapped[int | None] = mapped_column(nullable=True)
    goals: Mapped[int | None] = mapped_column(nullable=True)
    assists: Mapped[int | None] = mapped_column(nullable=True)
    shots: Mapped[int | None] = mapped_column(nullable=True)
    shots_on_target: Mapped[int | None] = mapped_column(nullable=True)
    passes: Mapped[int | None] = mapped_column(nullable=True)
    pass_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    key_passes: Mapped[int | None] = mapped_column(nullable=True)
    tackles: Mapped[int | None] = mapped_column(nullable=True)
    interceptions: Mapped[int | None] = mapped_column(nullable=True)
    clearances: Mapped[int | None] = mapped_column(nullable=True)
    blocks: Mapped[int | None] = mapped_column(nullable=True)
    yellow_cards: Mapped[int | None] = mapped_column(nullable=True)
    red_cards: Mapped[int | None] = mapped_column(nullable=True)
    fouls_committed: Mapped[int | None] = mapped_column(nullable=True)

    player: Mapped["Player"] = relationship()
    match: Mapped["Match"] = relationship()


class PlayerSeasonStatistic(Base, TimestampMixin):
    """A player's totals in one competition+season -- the source for both
    top-scorer tables and a player's season statistics. Always scoped to a
    (competition, season) so a past season is never presented as current."""

    __tablename__ = "player_season_statistics"
    __table_args__ = (
        UniqueConstraint(
            "player_id", "competition_id", "season", name="uq_player_season_statistics_player_comp_season"
        ),
        Index("ix_player_season_statistics_comp_season_goals", "competition_id", "season", "goals"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False
    )
    season: Mapped[str] = mapped_column(String(16), nullable=False)
    appearances: Mapped[int | None] = mapped_column(nullable=True)
    goals: Mapped[int] = mapped_column(default=0, nullable=False)
    assists: Mapped[int | None] = mapped_column(nullable=True)
    penalties: Mapped[int | None] = mapped_column(nullable=True)

    player: Mapped["Player"] = relationship()
    team: Mapped["Team | None"] = relationship()
    competition: Mapped["Competition"] = relationship()
