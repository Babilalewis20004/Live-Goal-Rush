"""Community features (Phase 6): comments, reactions, polls. PostgreSQL is the
source of truth for all of it; Redis holds only rebuildable aggregates."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    CommentStatus,
    CommentTarget,
    PollKind,
    PollStatus,
    ReactionKind,
    ReactionTarget,
    ReportStatus,
)


def _enum(cls, length: int = 16):
    return Enum(cls, native_enum=False, validate_strings=True, length=length)


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_target", "target_type", "target_id", "status", "created_at"),
        Index("ix_comments_parent", "parent_id"),
        Index("ix_comments_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_type: Mapped[CommentTarget] = mapped_column(_enum(CommentTarget), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), nullable=True)
    """Replies are one level deep: a reply to a reply attaches to the top-level comment."""
    body: Mapped[str] = mapped_column(Text, nullable=False)
    """Plain text -- never HTML. Clients render it as text, so there is nothing to sanitize *into*."""
    status: Mapped[CommentStatus] = mapped_column(_enum(CommentStatus), default=CommentStatus.VISIBLE, nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    report_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    moderated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])  # noqa: F821


class CommentLike(Base):
    __tablename__ = "comment_likes"
    __table_args__ = (UniqueConstraint("comment_id", "user_id", name="uq_comment_likes_comment_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CommentReport(Base):
    __tablename__ = "comment_reports"
    __table_args__ = (
        UniqueConstraint("comment_id", "reporter_id", name="uq_comment_reports_comment_reporter"),
        Index("ix_comment_reports_status", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[ReportStatus] = mapped_column(_enum(ReportStatus), default=ReportStatus.OPEN, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProfileReport(Base):
    """A report against a user's public profile (bio / display name)."""

    __tablename__ = "profile_reports"
    __table_args__ = (
        UniqueConstraint("profile_user_id", "reporter_id", name="uq_profile_reports_profile_reporter"),
        Index("ix_profile_reports_status", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[ReportStatus] = mapped_column(_enum(ReportStatus), default=ReportStatus.OPEN, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Reaction(Base):
    """One reaction per user per target (changing it replaces it)."""

    __tablename__ = "reactions"
    __table_args__ = (
        UniqueConstraint("user_id", "target_type", "target_id", name="uq_reactions_user_target"),
        Index("ix_reactions_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_type: Mapped[ReactionTarget] = mapped_column(_enum(ReactionTarget), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[ReactionKind] = mapped_column(_enum(ReactionKind), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Poll(Base):
    __tablename__ = "polls"
    __table_args__ = (
        Index("ix_polls_match", "match_id"),
        Index("ix_polls_article", "article_id"),
        Index("ix_polls_status_closes", "status", "closes_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[PollKind] = mapped_column(_enum(PollKind), nullable=False)
    status: Mapped[PollStatus] = mapped_column(_enum(PollStatus), default=PollStatus.OPEN, nullable=False)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    results_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    options: Mapped[list["PollOption"]] = relationship(
        back_populates="poll", cascade="all, delete-orphan", order_by="PollOption.position"
    )


class PollOption(Base):
    __tablename__ = "poll_options"
    __table_args__ = (UniqueConstraint("poll_id", "position", name="uq_poll_options_poll_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    poll: Mapped["Poll"] = relationship(back_populates="options")


class PollVote(Base):
    """One vote per user per poll; the unique constraint is what makes
    double-voting impossible, whatever the clients do."""

    __tablename__ = "poll_votes"
    __table_args__ = (UniqueConstraint("poll_id", "user_id", name="uq_poll_votes_poll_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    option_id: Mapped[int] = mapped_column(ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SocialNotificationLog(Base):
    """Idempotency ledger for community notifications (comment replies, poll
    results, editorial updates): `(user_id, dedup_key)` is unique."""

    __tablename__ = "social_notification_log"
    __table_args__ = (UniqueConstraint("user_id", "dedup_key", name="uq_social_notification_user_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
