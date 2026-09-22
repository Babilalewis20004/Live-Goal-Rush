from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DevicePlatform
from app.models.mixins import TimestampMixin


class Device(Base, TimestampMixin):
    """A registered push target (Phase 3 §16): one Expo push token OR one
    Web Push subscription triple, never both on the same row (the two
    token columns are mutually exclusive per `platform`). Partial unique
    indexes (not a plain `UniqueConstraint`, since the column is nullable
    and most rows leave the *other* platform's column null) enforce that a
    given token/endpoint is only ever registered once."""

    __tablename__ = "devices"
    __table_args__ = (
        Index(
            "uq_devices_expo_push_token",
            "expo_push_token",
            unique=True,
            postgresql_where=text("expo_push_token IS NOT NULL"),
        ),
        Index(
            "uq_devices_web_push_endpoint",
            "web_push_endpoint",
            unique=True,
            postgresql_where=text("web_push_endpoint IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[DevicePlatform] = mapped_column(
        Enum(DevicePlatform, native_enum=False, validate_strings=True, length=32), nullable=False
    )
    expo_push_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    web_push_endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    web_push_p256dh: Mapped[str | None] = mapped_column(String(255), nullable=True)
    web_push_auth: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
