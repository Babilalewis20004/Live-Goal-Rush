from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Boolean, Enum, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import UserRole
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_email_lower", text("lower(email)")),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, validate_strings=True, length=16),
        default=UserRole.USER,
        server_default=UserRole.USER.name,
        nullable=False,
    )
    """Content authorization (discovery). Not self-service -- see `app/cli.py`."""
    profile_public: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    """Opt-in: until true, nobody but the user can see anything about them."""
    bio: Mapped[str | None] = mapped_column(String(280), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Set by a moderator/admin; a suspended user cannot sign in or post."""
    suspended_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Set when the user erased their account (`DELETE /users/me`): personal data is scrubbed and the row is
    kept only so billing records that must be retained keep their reference."""
