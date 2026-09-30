from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Player(Base, TimestampMixin):
    __tablename__ = "players"
    __table_args__ = (
        # Trigram index so `ILIKE '%q%'` search (football_service.search)
        # doesn't sequentially scan the table. Needs the `pg_trgm`
        # extension -- created by the Phase 4 migration.
        Index(
            "ix_players_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    position: Mapped[str | None] = mapped_column(String(50), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shirt_number: Mapped[int | None] = mapped_column(nullable=True)
    """Current shirt number for the player's current team (squad data). A
    match's shirt number lives on `LineupPlayer` -- it can differ."""
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    profile_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When a provider profile/squad call last populated this row (as
    opposed to it merely being created from a match event or a search hit,
    which only carries a name). Drives "should a profile sync be queued?"."""

    team: Mapped["Team | None"] = relationship(back_populates="players")
