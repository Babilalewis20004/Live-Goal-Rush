"""Operational records (Phase 7): failed background jobs and the administrative audit trail."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FailedJob(Base):
    """A Celery task that raised and will not run again (retries exhausted, or a permanent error). The
    dead-letter record: nothing a worker gives up on is silently dropped. Administrators list these via
    `GET /api/v1/admin/failed-jobs` and mark them resolved once handled (or after re-running the task)."""

    __tablename__ = "failed_jobs"
    __table_args__ = (
        Index("ix_failed_jobs_failed_at", "failed_at"),
        Index("ix_failed_jobs_task_failed", "task_name", "failed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_type: Mapped[str] = mapped_column(String(120), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """Truncated and scrubbed of anything that looks like a credential."""
    classification: Mapped[str] = mapped_column(String(24), nullable=False)
    """temporary | database | validation | authentication | permanent -- see app/worker/failure.py."""
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    """A task failing the same way on every beat tick is one row with a count, not thousands of rows."""
    entity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    """What the task was working on, e.g. `match:123`, when its arguments say."""
    args_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AuditLog(Base):
    """Append-only record of sensitive administrative actions: who did what to whom, when, and why.
    Nothing in the application updates or deletes a row. `actor_id` goes NULL if the actor's account is
    erased, but `actor_label` keeps a non-identifying description so the entry stays meaningful."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_created", "created_at"),
        Index("ix_audit_log_target", "target_type", "target_id", "created_at"),
        Index("ix_audit_log_actor", "actor_id", "created_at"),
        Index("ix_audit_log_action", "action", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(64), nullable=False)
    """`user:12 (admin)` or `cli` -- never an email address."""
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """Small structured context (old/new role, ...). Never secrets or free-text user content."""
