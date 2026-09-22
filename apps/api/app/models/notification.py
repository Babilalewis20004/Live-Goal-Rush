from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.events.schemas import RealtimeEventType
from app.models.enums import NotificationScope
from app.models.mixins import TimestampMixin


class NotificationPreference(Base, TimestampMixin):
    """An explicit override on top of the default-on event set (Phase 3
    §14/§21) -- see `services/notification_dispatch_service.py` for the
    "favouriting something implies default notifications unless an
    explicit `enabled=False` row exists" rule this table backs. Reuses
    `RealtimeEventType` (the same provider-agnostic event enum the
    real-time pipeline already publishes) rather than inventing a parallel
    notification-specific type -- there is exactly one vocabulary for "what
    happened to a match" in this codebase.
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (
        # `postgresql_nulls_not_distinct`: plain Postgres uniqueness treats
        # every NULL as distinct from every other NULL, which would let a
        # GLOBAL preference (scope_id IS NULL) be inserted more than once
        # for the same (user, event_type) -- this makes NULL scope_id
        # participate in the uniqueness check like any other value, so the
        # upsert-by-conflict in `notification_preferences_service.py`
        # actually catches it.
        UniqueConstraint(
            "user_id",
            "scope_type",
            "scope_id",
            "event_type",
            name="uq_notification_preferences_scope_event",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_type: Mapped[NotificationScope] = mapped_column(
        Enum(NotificationScope, native_enum=False, validate_strings=True, length=32), nullable=False
    )
    # Null for GLOBAL; a team/competition/match id for the other scopes.
    scope_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[RealtimeEventType] = mapped_column(
        Enum(RealtimeEventType, native_enum=False, validate_strings=True, length=32), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class NotificationLog(Base, TimestampMixin):
    """Idempotency ledger (Phase 3 §15) -- `UniqueConstraint(user_id,
    dedup_key)` is the actual dedup mechanism: dispatch does one bulk
    `INSERT ... ON CONFLICT DO NOTHING RETURNING user_id`, and only the
    rows that didn't already exist come back as "actually deliver this."
    Survives a duplicated provider event, a retried Celery task, or a
    worker restart identically -- all three just look like "this
    (user, dedup_key) pair already has a row."""

    __tablename__ = "notification_log"
    __table_args__ = (UniqueConstraint("user_id", "dedup_key", name="uq_notification_log_user_dedup"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
