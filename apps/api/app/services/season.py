"""Season labels (Phase 4).

The app has no Season entity: a season is a short label ("2026/27") stored
next to whatever it scopes (standings rows, player season statistics). When
a provider doesn't state the season, the European-calendar convention below
is used -- a season starts in July. A provider that knows better (e.g. a
southern-hemisphere or calendar-year league) simply supplies its own label.
"""

from __future__ import annotations

from datetime import date, datetime, timezone


def current_season_label(today: date | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    start = today.year if today.month >= 7 else today.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


SEASON_LABEL_PATTERN = r"^\d{4}(/\d{2})?$"
"""A season label as stored: "2026/27" (spans two calendar years) or "2026"."""

MAX_HISTORY_YEARS = 10


def season_start_year(label: str) -> int | None:
    import re

    if not re.match(SEASON_LABEL_PATTERN, label):
        return None
    return int(label[:4])


def is_requestable_past_season(label: str, today: date | None = None) -> bool:
    """Whether a client-supplied season label is worth asking a provider for:
    well-formed, not in the future and not absurdly old. Guards the on-demand
    history sync from being driven by arbitrary strings."""
    start = season_start_year(label)
    if start is None:
        return False
    current = season_start_year(current_season_label(today))
    return current is not None and current - MAX_HISTORY_YEARS <= start <= current
