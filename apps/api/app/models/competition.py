from __future__ import annotations

from sqlalchemy import Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import CompetitionType
from app.models.mixins import TimestampMixin


class Competition(Base, TimestampMixin):
    __tablename__ = "competitions"
    __table_args__ = (
        Index(
            "ix_competitions_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    type: Mapped[CompetitionType] = mapped_column(
        Enum(CompetitionType, native_enum=False, validate_strings=True, length=32),
        default=CompetitionType.LEAGUE,
        nullable=False,
    )

    matches: Mapped[list["Match"]] = relationship(back_populates="competition")
