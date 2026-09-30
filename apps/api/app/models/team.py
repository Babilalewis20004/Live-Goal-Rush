from __future__ import annotations

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Team(Base, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (
        Index(
            "ix_teams_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    short_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    venue: Mapped[str | None] = mapped_column(String(255), nullable=True)

    players: Mapped[list["Player"]] = relationship(back_populates="team")
