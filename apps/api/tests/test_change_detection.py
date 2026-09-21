"""Pure unit tests for change detection (Phase 2 §11) -- no DB, no Redis."""

from datetime import datetime, timezone

from app.events.schemas import RealtimeEventType
from app.schemas.competition import CompetitionOut
from app.schemas.match import MatchDetail, MatchEventOut
from app.schemas.team import TeamOut
from app.services.change_detection import build_state_snapshot, detect_changes

_COMPETITION = CompetitionOut(id=1, name="Premier League", country="England", logo_url=None, type="league")
_HOME = TeamOut(id=1, name="Arsenal", short_name="ARS", country="England", logo_url=None)
_AWAY = TeamOut(id=2, name="Chelsea", short_name="CHE", country="England", logo_url=None)


def _match(
    *, status="live", home_score=1, away_score=1, minute=62, events=None, last_synced_at=None
) -> MatchDetail:
    return MatchDetail(
        id=123,
        competition=_COMPETITION,
        home_team=_HOME,
        away_team=_AWAY,
        kickoff_time=datetime(2026, 9, 21, 19, 0, tzinfo=timezone.utc),
        status=status,
        home_score=home_score,
        away_score=away_score,
        half_time_home_score=None,
        half_time_away_score=None,
        minute=minute,
        venue=None,
        last_synced_at=last_synced_at or datetime.now(timezone.utc),
        events=events or [],
    )


def _event(id_: int, event_type="goal", minute=10) -> MatchEventOut:
    return MatchEventOut(
        id=id_, event_type=event_type, minute=minute, extra_minute=None, team=_HOME, player=None,
        assist_player=None, description=None,
    )


def test_no_previous_state_and_match_not_live_publishes_nothing():
    assert detect_changes(_match(status="scheduled"), previous=None) == []


def test_no_previous_state_but_already_live_announces_match_updated():
    events = detect_changes(_match(status="live"), previous=None)
    assert [e.type for e in events] == [RealtimeEventType.MATCH_UPDATED]


def test_identical_state_produces_no_events():
    match = _match(home_score=1, away_score=1, minute=62)
    previous = build_state_snapshot(match)
    assert detect_changes(match, previous) == []


def test_score_change_produces_match_updated():
    previous = build_state_snapshot(_match(home_score=1, away_score=1, minute=62))
    new_match = _match(home_score=2, away_score=1, minute=63)
    events = detect_changes(new_match, previous)
    assert [e.type for e in events] == [RealtimeEventType.MATCH_UPDATED]
    assert events[0].data["home_score"] == 2


def test_minute_only_change_produces_match_updated():
    previous = build_state_snapshot(_match(minute=62))
    events = detect_changes(_match(minute=63), previous)
    assert [e.type for e in events] == [RealtimeEventType.MATCH_UPDATED]


def test_new_goal_event_produces_goal_not_generic_update():
    previous_match = _match(events=[_event(1, "goal", 10)])
    previous = build_state_snapshot(previous_match)
    new_match = _match(home_score=2, events=[_event(1, "goal", 10), _event(2, "goal", 55)])
    events = detect_changes(new_match, previous)
    assert [e.type for e in events] == [RealtimeEventType.GOAL]
    assert events[0].data["event"]["id"] == 2


def test_new_card_event_produces_card():
    previous = build_state_snapshot(_match(events=[]))
    new_match = _match(events=[_event(1, "yellow_card", 30)])
    events = detect_changes(new_match, previous)
    assert [e.type for e in events] == [RealtimeEventType.CARD]


def test_new_substitution_event_produces_substitution():
    previous = build_state_snapshot(_match(events=[]))
    new_match = _match(events=[_event(1, "substitution", 70)])
    events = detect_changes(new_match, previous)
    assert [e.type for e in events] == [RealtimeEventType.SUBSTITUTION]


def test_status_transition_to_halftime():
    previous = build_state_snapshot(_match(status="live"))
    events = detect_changes(_match(status="halftime"), previous)
    assert [e.type for e in events] == [RealtimeEventType.HALF_TIME]


def test_status_transition_scheduled_to_live_is_match_started():
    previous = build_state_snapshot(_match(status="scheduled"))
    events = detect_changes(_match(status="live"), previous)
    assert [e.type for e in events] == [RealtimeEventType.MATCH_STARTED]


def test_status_transition_halftime_to_live_is_second_half_started():
    previous = build_state_snapshot(_match(status="halftime"))
    events = detect_changes(_match(status="live"), previous)
    assert [e.type for e in events] == [RealtimeEventType.SECOND_HALF_STARTED]


def test_status_transition_to_finished():
    previous = build_state_snapshot(_match(status="live"))
    events = detect_changes(_match(status="finished", minute=None), previous)
    assert [e.type for e in events] == [RealtimeEventType.MATCH_FINISHED]


def test_all_events_carry_match_id_as_string():
    previous = build_state_snapshot(_match(status="live"))
    events = detect_changes(_match(status="finished", minute=None), previous)
    assert events[0].match_id == "123"
