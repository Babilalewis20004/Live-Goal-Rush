"""The internal real-time event structure (Phase 2 §12).

Published by the worker's change-detection step onto Redis Pub/Sub
(`RedisKeys.MATCH_EVENTS_CHANNEL`) and consumed by the WebSocket pub/sub
bridge, which is the only thing that turns these into outbound WebSocket
messages -- the worker never knows a WebSocket exists (spec §13).
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class RealtimeEventType(str, enum.Enum):
    MATCH_STARTED = "MATCH_STARTED"
    MATCH_UPDATED = "MATCH_UPDATED"
    GOAL = "GOAL"
    CARD = "CARD"
    SUBSTITUTION = "SUBSTITUTION"
    HALF_TIME = "HALF_TIME"
    SECOND_HALF_STARTED = "SECOND_HALF_STARTED"
    MATCH_FINISHED = "MATCH_FINISHED"
    MATCH_POSTPONED = "MATCH_POSTPONED"
    MATCH_CANCELLED = "MATCH_CANCELLED"
    # Phase 4: match-centre data changed (see change_detection.py). Never
    # notified (not in DEFAULT_ON_EVENT_TYPES) -- they only refresh open
    # match-centre screens.
    LINEUP_UPDATED = "LINEUP_UPDATED"
    STATISTICS_UPDATED = "STATISTICS_UPDATED"


class RealtimeEvent(BaseModel):
    type: RealtimeEventType
    match_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any]
