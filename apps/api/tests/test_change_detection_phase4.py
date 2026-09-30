"""Phase 4 change detection: LINEUP_UPDATED / STATISTICS_UPDATED fire only
when the stored data genuinely differs from what was last published."""

from datetime import datetime, timezone

from app.events.schemas import RealtimeEventType
from app.schemas.competition import CompetitionOut
from app.schemas.match import MatchDetail
from app.schemas.team import TeamOut
from app.services.change_detection import build_state_snapshot, detect_changes

TEAM_A = TeamOut(id=1, name="A", short_name="A", country=None, logo_url=None)
TEAM_B = TeamOut(id=2, name="B", short_name="B", country=None, logo_url=None)


def _match(status="live", home=0, away=0, minute=10) -> MatchDetail:
    return MatchDetail(
        id=7,
        competition=CompetitionOut(id=1, name="L", country=None, logo_url=None, type="league"),
        home_team=TEAM_A,
        away_team=TEAM_B,
        kickoff_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        status=status,
        home_score=home,
        away_score=away,
        half_time_home_score=None,
        half_time_away_score=None,
        minute=minute,
        venue=None,
        last_synced_at=datetime.now(timezone.utc),
        events=[],
    )


STATS = {"home": {"team_id": 1, "shots": 3, "possession": 55.0}, "away": {"team_id": 2, "shots": 1, "possession": 45.0}}


def _types(events) -> list[RealtimeEventType]:
    return [e.type for e in events]


def test_snapshot_only_includes_phase4_keys_when_data_exists():
    match = _match()
    assert set(build_state_snapshot(match)) == {"status", "home_score", "away_score", "minute", "event_ids"}
    snapshot = build_state_snapshot(match, lineup_fingerprint="abc", statistics=STATS)
    assert snapshot["lineup_fingerprint"] == "abc" and snapshot["statistics"] == STATS


def test_new_lineup_fires_lineup_updated():
    match = _match()
    previous = build_state_snapshot(match)
    events = detect_changes(match, previous, lineup_fingerprint="abc")
    assert _types(events) == [RealtimeEventType.LINEUP_UPDATED]
    assert events[0].match_id == "7" and events[0].data["status"] == "live"


def test_unchanged_lineup_and_statistics_publish_nothing():
    match = _match()
    previous = build_state_snapshot(match, lineup_fingerprint="abc", statistics=STATS)
    assert detect_changes(match, previous, lineup_fingerprint="abc", statistics=dict(STATS)) == []


def test_changed_lineup_fires_again():
    match = _match()
    previous = build_state_snapshot(match, lineup_fingerprint="abc")
    assert _types(detect_changes(match, previous, lineup_fingerprint="def")) == [RealtimeEventType.LINEUP_UPDATED]


def test_statistics_change_fires_statistics_updated_with_the_numbers():
    match = _match()
    previous = build_state_snapshot(match, statistics=STATS)
    newer = {**STATS, "home": {**STATS["home"], "shots": 4}}
    events = detect_changes(match, previous, statistics=newer)
    assert _types(events) == [RealtimeEventType.STATISTICS_UPDATED]
    assert events[0].data["statistics"]["home"]["shots"] == 4
    assert events[0].data["home_score"] == 0  # still carries the base fields clients already read


def test_provider_without_the_data_never_fires_phase4_events():
    match = _match()
    previous = build_state_snapshot(match)
    assert detect_changes(match, previous, lineup_fingerprint=None, statistics=None) == []


def test_cold_start_announces_nothing_extra():
    match = _match()
    events = detect_changes(match, None, lineup_fingerprint="abc", statistics=STATS)
    assert _types(events) == [RealtimeEventType.MATCH_UPDATED]


def test_phase4_events_accompany_not_replace_existing_ones():
    before = _match(minute=10)
    after = _match(minute=11, home=1)
    previous = build_state_snapshot(before, statistics=STATS)
    newer = {**STATS, "home": {**STATS["home"], "shots": 4}}
    events = detect_changes(after, previous, statistics=newer)
    assert _types(events) == [RealtimeEventType.MATCH_UPDATED, RealtimeEventType.STATISTICS_UPDATED]


def test_full_time_still_announced_alongside_final_statistics():
    previous = build_state_snapshot(_match(), statistics=STATS)
    newer = {**STATS, "home": {**STATS["home"], "shots": 9}}
    events = detect_changes(_match(status="finished", home=2), previous, statistics=newer)
    assert _types(events) == [RealtimeEventType.MATCH_FINISHED, RealtimeEventType.STATISTICS_UPDATED]


def test_new_event_types_do_not_break_the_notification_preference_enum():
    from app.services.notification_dispatch_service import DEFAULT_ON_EVENT_TYPES

    assert RealtimeEventType.LINEUP_UPDATED.value == "LINEUP_UPDATED"
    assert RealtimeEventType.STATISTICS_UPDATED.value == "STATISTICS_UPDATED"
    # match-centre refresh signals must never push-notify anyone by default
    assert not ({RealtimeEventType.LINEUP_UPDATED, RealtimeEventType.STATISTICS_UPDATED} & DEFAULT_ON_EVENT_TYPES)
