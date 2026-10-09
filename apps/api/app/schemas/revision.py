from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import RevisionAction


class RevisionOut(BaseModel):
    version: int
    action: RevisionAction
    editor_name: str | None
    """Display name only; None for changes made by the system (scheduled publishing)."""
    created_at: datetime
    changes: list[str] = Field(default_factory=list)
    """Which fields differ from the previous version."""


class RevisionDetail(RevisionOut):
    snapshot: dict[str, Any]


class FieldChange(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class DiffLine(BaseModel):
    kind: Literal["add", "del", "ctx"]
    text: str


class RevisionDiff(BaseModel):
    article_id: int
    from_version: int
    to_version: int
    changes: list[FieldChange] = Field(default_factory=list)
    content_diff: list[DiffLine] = Field(default_factory=list)
    """Line-level diff of the article body, one line per paragraph/heading/item."""


class ScheduleIn(BaseModel):
    publish_at: datetime
    unpublish_at: datetime | None = None


class ApproveIn(BaseModel):
    publish_at: datetime | None = None
    """Omit to publish immediately; give a future time to schedule."""
    unpublish_at: datetime | None = None


class RejectIn(BaseModel):
    note: str = Field(default="", max_length=500)
