"""Engagement analytics and per-user search history (discovery)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EngagementBucket(Base):
    """Hourly counts per (entity, signal), written by the aggregation job from
    Redis counters -- the request path never touches this table. Only counts:
    no user id, no IP, nothing personal."""

    __tablename__ = "engagement_buckets"
    __table_args__ = (Index("ix_engagement_buckets_entity_bucket", "entity_type", "bucket"),)

    entity_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    entity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal: Mapped[str] = mapped_column(String(16), primary_key=True)
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RecentSearch(Base):
    """A signed-in user's own recent searches (the newest 10 are kept).
    Deleted with the user; never read on behalf of anyone else."""

    __tablename__ = "recent_searches"
    __table_args__ = (UniqueConstraint("user_id", "query", name="uq_recent_searches_user_query"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query: Mapped[str] = mapped_column(String(100), nullable=False)
    last_searched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
