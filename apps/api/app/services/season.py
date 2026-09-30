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
