# Phase 2: /matches/* endpoints are now cache-aside reads against the
# database (populated by the background worker / startup seed), not
# sync-on-read against the provider (see football_service.py) -- so these
# tests use `seeded_client` to pre-populate the database first, the same
# way the app's startup lifespan does in a real deployment.


async def test_live_matches_endpoint(seeded_client):
    resp = await seeded_client.get("/api/v1/matches/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data
    assert all(m["status"] in ("live", "halftime") for m in data)


async def test_live_matches_includes_freshness_metadata(seeded_client):
    resp = await seeded_client.get("/api/v1/matches/live")
    match = resp.json()[0]
    assert match["last_synced_at"] is not None
    assert match["data_status"] == "FRESH"


async def test_today_matches_endpoint(seeded_client):
    resp = await seeded_client.get("/api/v1/matches/today")
    assert resp.status_code == 200
    assert len(resp.json()) > 0


async def test_upcoming_matches_endpoint(seeded_client):
    resp = await seeded_client.get("/api/v1/matches/upcoming")
    assert resp.status_code == 200
    data = resp.json()
    assert data
    assert all(m["status"] == "scheduled" for m in data)


async def test_live_matches_are_empty_but_not_an_error_before_any_sync(client):
    # A cold, never-synced database is the honest Phase 2 state before the
    # worker's first sync cycle (or startup seed) has run -- it must not
    # crash, and must not fabricate data (spec §21/§22).
    resp = await client.get("/api/v1/matches/live")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_match_detail_includes_event_timeline(seeded_client):
    # A live match's event list is real-time-evolving with the mock
    # provider (architecture/realtime.md) -- it can legitimately be empty
    # in the seconds right after "kickoff" in its simulated cycle, same as
    # a real match with no goals yet. This asserts the timeline is
    # correctly *wired up* (a list of well-shaped events when there are
    # any), not that a live match always has scored -- that's what
    # test_mock_provider.py::test_finished_match_events_are_fully_revealed
    # asserts deterministically against a non-time-evolving fixture.
    live = (await seeded_client.get("/api/v1/matches/live")).json()
    match_id = live[0]["id"]

    resp = await seeded_client.get(f"/api/v1/matches/{match_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == match_id
    assert isinstance(detail["events"], list)
    assert all("event_type" in e and "minute" in e for e in detail["events"])


async def test_match_events_endpoint(seeded_client):
    live = (await seeded_client.get("/api/v1/matches/live")).json()
    match_id = live[0]["id"]

    resp = await seeded_client.get(f"/api/v1/matches/{match_id}/events")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_unknown_match_returns_404_with_friendly_message(client):
    resp = await client.get("/api/v1/matches/999999")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Match not found"}


async def test_unknown_match_events_returns_404(client):
    resp = await client.get("/api/v1/matches/999999/events")
    assert resp.status_code == 404
