"""Change detection (Phase 2 §11).

Compares a freshly-synced match against the last state that was published
for it, and returns the realtime events (if any) that should be broadcast.
A poll that finds nothing different from the last poll publishes nothing --
change detection is what keeps Redis Pub/Sub (and therefore every
WebSocket connection) from being flooded with a message per poll interval
regardless of whether anything actually changed.

The "previous state" is read from/written to Redis
(`RedisKeys.match_state`), not derived from Postgres, so it's independent
of transaction/read timing and cheap to check on every poll.
"""

from __future__ import annotations

from app.events.schemas import RealtimeEvent, RealtimeEventType
from app.models.enums import MatchEventType, MatchStatus
from app.schemas.match import MatchDetail, MatchEventOut

_CARD_TYPES = {MatchEventType.YELLOW_CARD.value, MatchEventType.RED_CARD.value}
_GOAL_TYPES = {MatchEventType.GOAL.value, MatchEventType.OWN_GOAL.value, MatchEventType.PENALTY.value}

_STATUS_TRANSITION_TYPES = {
    MatchStatus.HALFTIME.value: RealtimeEventType.HALF_TIME,
    MatchStatus.FINISHED.value: RealtimeEventType.MATCH_FINISHED,
    MatchStatus.POSTPONED.value: RealtimeEventType.MATCH_POSTPONED,
    MatchStatus.CANCELLED.value: RealtimeEventType.MATCH_CANCELLED,
}


def build_state_snapshot(
    match: MatchDetail, *, lineup_fingerprint: str | None = None, statistics: dict | None = None
) -> dict:
    """The minimal normalized shape change detection diffs against; stored
    with no TTL (overwritten on every sync) as "previous state" input for
    the next poll. The Phase 4 keys are only present when the provider
    supplied that data, so a provider without lineups/statistics never
    produces LINEUP_UPDATED/STATISTICS_UPDATED."""
    snapshot: dict = {
        "status": match.status,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "minute": match.minute,
        "event_ids": [e.id for e in match.events],
    }
    if lineup_fingerprint is not None:
        snapshot["lineup_fingerprint"] = lineup_fingerprint
    if statistics is not None:
        snapshot["statistics"] = statistics
    return snapshot


def detect_changes(
    match: MatchDetail,
    previous: dict | None,
    *,
    lineup_fingerprint: str | None = None,
    statistics: dict | None = None,
) -> list[RealtimeEvent]:
    if previous is None:
        # First time this match has been seen by change detection (e.g.
        # worker just started). Only announce it if it's already in
        # progress -- a cold start isn't a real "the match just kicked off"
        # transition worth broadcasting.
        if match.status == MatchStatus.LIVE.value:
            return [_match_updated(match)]
        return []

    events: list[RealtimeEvent] = []
    status_changed = previous.get("status") != match.status
    score_changed = (
        previous.get("home_score") != match.home_score or previous.get("away_score") != match.away_score
    )
    minute_changed = previous.get("minute") != match.minute
    previous_event_ids = set(previous.get("event_ids", []))
    new_events = [e for e in match.events if e.id not in previous_event_ids]

    if status_changed:
        events.append(_status_transition_event(match, previous.get("status")))

    for event in new_events:
        events.append(_event_added(match, event))

    if not status_changed and not new_events and (score_changed or minute_changed):
        events.append(_match_updated(match))

    # Phase 4: only when the stored data genuinely differs from what was
    # last published -- an unchanged poll publishes nothing.
    if lineup_fingerprint is not None and lineup_fingerprint != previous.get("lineup_fingerprint"):
        events.append(
            RealtimeEvent(type=RealtimeEventType.LINEUP_UPDATED, match_id=str(match.id), data=_base_data(match))
        )
    if statistics is not None and statistics != previous.get("statistics"):
        data = _base_data(match)
        data["statistics"] = statistics
        events.append(RealtimeEvent(type=RealtimeEventType.STATISTICS_UPDATED, match_id=str(match.id), data=data))

    return events


def _base_data(match: MatchDetail) -> dict:
    return {
        "home_score": match.home_score,
        "away_score": match.away_score,
        "status": match.status,
        "minute": match.minute,
    }


def _match_updated(match: MatchDetail) -> RealtimeEvent:
    return RealtimeEvent(type=RealtimeEventType.MATCH_UPDATED, match_id=str(match.id), data=_base_data(match))


def _status_transition_event(match: MatchDetail, previous_status: str | None) -> RealtimeEvent:
    if match.status == MatchStatus.LIVE.value:
        event_type = (
            RealtimeEventType.MATCH_STARTED
            if previous_status == MatchStatus.SCHEDULED.value
            else RealtimeEventType.SECOND_HALF_STARTED
        )
    else:
        event_type = _STATUS_TRANSITION_TYPES.get(match.status, RealtimeEventType.MATCH_UPDATED)
    return RealtimeEvent(type=event_type, match_id=str(match.id), data=_base_data(match))


def _event_added(match: MatchDetail, event: MatchEventOut) -> RealtimeEvent:
    if event.event_type in _GOAL_TYPES:
        event_type = RealtimeEventType.GOAL
    elif event.event_type in _CARD_TYPES:
        event_type = RealtimeEventType.CARD
    elif event.event_type == MatchEventType.SUBSTITUTION.value:
        event_type = RealtimeEventType.SUBSTITUTION
    else:
        event_type = RealtimeEventType.MATCH_UPDATED

    data = _base_data(match)
    data["event"] = {
        "id": event.id,
        "event_type": event.event_type,
        "minute": event.minute,
        "extra_minute": event.extra_minute,
        "team_id": event.team.id if event.team else None,
        "player": event.player.name if event.player else None,
        # Phase 4: enough for a client to render the timeline entry fully
        # without a refetch -- for a substitution `player` is who came on and
        # `assist` who went off (same convention as MatchEventOut).
        "assist": event.assist_player.name if event.assist_player else None,
        "description": event.description,
        "event_detail": event.event_detail,
    }
    return RealtimeEvent(type=event_type, match_id=str(match.id), data=data)
