from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ContentNotificationKind
from app.models.mixins import TimestampMixin


class ContentNotificationPreference(Base, TimestampMixin):
    """A user's explicit choice for one kind of article notification. No row =
    that kind's conservative default (`content_notification_service`)."""

    __tablename__ = "content_notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_content_notification_pref_user_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ContentNotificationKind] = mapped_column(
        Enum(ContentNotificationKind, native_enum=False, validate_strings=True, length=24), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ContentNotificationLog(Base):
    """Idempotency ledger, like `NotificationLog` but for articles (that
    table's `match_id` is NOT NULL, so articles get their own). The
    `(user_id, article_id)` uniqueness is the dedup; `created_at` also backs
    the per-user daily cap."""

    __tablename__ = "content_notification_log"
    __table_args__ = (UniqueConstraint("user_id", "article_id", name="uq_content_notification_log_user_article"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
