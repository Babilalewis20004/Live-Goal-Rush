from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import RevisionAction


class ArticleRevision(Base):
    """One saved version of an article. `snapshot` is the complete editable
    state at that moment (so any version can be restored or compared without
    replaying history); `changes` lists which fields differ from the previous
    version. Append-only: nothing edits or deletes a revision (they go when the
    article does)."""

    __tablename__ = "article_revisions"
    __table_args__ = (UniqueConstraint("article_id", "version", name="uq_article_revisions_article_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    editor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    """NULL when the system made the change (scheduled publishing)."""
    action: Mapped[RevisionAction] = mapped_column(
        Enum(RevisionAction, native_enum=False, validate_strings=True, length=16), nullable=False
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
