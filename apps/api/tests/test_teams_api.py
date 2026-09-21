# Team ids below are deterministic: sync_all_competitions_and_fixtures walks
# competitions in COMPETITIONS dict order and, within each, teams in the
# order they first appear in FIXTURES (see mock_data.py). Team 1 is always
# Real Madrid; team 11 (Manchester United, epl-3) always has a finished
# result; team 13 (Brighton, epl-4) always has one scheduled fixture.


async def test_get_team_detail(seeded_client):
    resp = await seeded_client.get("/api/v1/teams/1")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Real Madrid"


async def test_team_results_only_includes_finished_matches(seeded_client):
    resp = await seeded_client.get("/api/v1/teams/11/results")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["status"] == "finished"


async def test_team_fixtures_only_includes_scheduled_matches(seeded_client):
    resp = await seeded_client.get("/api/v1/teams/13/fixtures")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["status"] == "scheduled"


async def test_unknown_team_returns_404(client):
    resp = await client.get("/api/v1/teams/99999")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Team not found"}


async def test_unknown_team_fixtures_returns_404(client):
    resp = await client.get("/api/v1/teams/99999/fixtures")
    assert resp.status_code == 404


async def test_unknown_team_results_returns_404(client):
    resp = await client.get("/api/v1/teams/99999/results")
    assert resp.status_code == 404
