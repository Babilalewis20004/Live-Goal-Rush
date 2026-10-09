"""Community/analytics events on the existing real-time channel (Phase 6b).

These ride the same Redis pub/sub channel and WebSocket manager as live match
events -- there is no second real-time system. They carry only ids and counts
(clients refetch through the normal, permission-checked API) and are delivered
to sockets watching *that match* only, never to the general livescore feed.

Best effort and throttled: a Redis hiccup must never fail a comment or a vote,
and a burst of reactions becomes one nudge every couple of seconds.
"""

from __future__ import annotations

import logging

from app.core.redis_keys import RedisKeys
from app.events.schemas import RealtimeEvent, RealtimeEventType

logger = logging.getLogger(__name__)

THROTTLE_SECONDS = 2
COMMUNITY_EVENT_TYPES = frozenset(
    {
        RealtimeEventType.COMMENT_CREATED,
        RealtimeEventType.COMMENT_REACTION,
        RealtimeEventType.POLL_UPDATED,
        RealtimeEventType.MATCH_INSIGHT_UPDATED,
        RealtimeEventType.PREDICTION_UPDATED,
    }
)


async def publish_match_event(redis, event_type: RealtimeEventType, match_id: int, throttle: bool = True, **data) -> bool:
    """Returns True if the event was published."""
    if redis is None:
        return False
    try:
        if throttle:
            ok = await redis.raw.set(f"football:rt:throttle:{event_type.value}:{match_id}", "1", nx=True, ex=THROTTLE_SECONDS)
            if not ok:
                return False
        event = RealtimeEvent(type=event_type, match_id=str(match_id), data=data)
        await redis.publish(RedisKeys.MATCH_EVENTS_CHANNEL, event.model_dump(mode="json"))
        return True
    except Exception:
        logger.warning("could not publish %s for match %s", event_type.value, match_id, exc_info=True)
        return False
