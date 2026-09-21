import enum
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class DataStatus(str, enum.Enum):
    """Phase 2 §21: whether the data being returned reflects a recent
    provider sync (`FRESH`), an overdue-but-still-served one (`STALE`, e.g.
    the worker/provider is temporarily behind), or no sync has ever
    succeeded (`UNAVAILABLE`). Computed per-match from `last_synced_at`
    (see `MatchSummary.data_status`), not stored."""

    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
