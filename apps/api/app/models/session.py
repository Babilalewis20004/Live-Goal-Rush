from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class RefreshToken(Base, TimestampMixin):
    """A single issued refresh token (Phase 3 §5). Only its SHA-256 hash is
    stored -- never the raw token -- so a database leak alone can't be
    replayed. Rotation + reuse detection: every `/auth/refresh` call revokes
    this row and links `replaced_by_id` to the newly-issued one; presenting
    an already-revoked token again revokes the whole chain for that user
    (the standard defense against a stolen-then-replayed refresh token)."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        # `replaced_by_id` is a self-referencing ON DELETE SET NULL key. Without an index every deleted token
        # scanned the whole table to null out references: purging 18,675 expired tokens from 80,000 took 186 s
        # (1.2 s with the index), and the same trigger slows account deletion and session cleanup.
        Index("ix_refresh_tokens_replaced_by", "replaced_by_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PasswordResetToken(Base, TimestampMixin):
    """Single-use, time-limited password reset token (Phase 3 §5). Also
    stored only as a SHA-256 hash, matching `RefreshToken`."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
