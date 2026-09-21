async def test_live_matches_endpoint(client):
    resp = await client.get("/api/v1/matches/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data
    assert all(m["status"] in ("live", "halftime") for m in data)


async def test_today_matches_endpoint(client):
    resp = await client.get("/api/v1/matches/today")
    assert resp.status_code == 200
    assert len(resp.json()) > 0


async def test_upcoming_matches_endpoint(client):
    resp = await client.get("/api/v1/matches/upcoming")
    assert resp.status_code == 200
    data = resp.json()
    assert data
    assert all(m["status"] == "scheduled" for m in data)


async def test_match_detail_includes_event_timeline(client):
    live = (await client.get("/api/v1/matches/live")).json()
    match_id = live[0]["id"]

    resp = await client.get(f"/api/v1/matches/{match_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == match_id
    assert isinstance(detail["events"], list)
    assert detail["events"]


async def test_match_events_endpoint(client):
    live = (await client.get("/api/v1/matches/live")).json()
    match_id = live[0]["id"]

    resp = await client.get(f"/api/v1/matches/{match_id}/events")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_unknown_match_returns_404_with_friendly_message(client):
    resp = await client.get("/api/v1/matches/999999")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Match not found"}


async def test_unknown_match_events_returns_404(client):
    resp = await client.get("/api/v1/matches/999999/events")
    assert resp.status_code == 404
