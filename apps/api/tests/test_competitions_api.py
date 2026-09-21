async def test_list_competitions_returns_all_six(client):
    resp = await client.get("/api/v1/competitions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 6
    assert len(data["items"]) == 6


async def test_list_competitions_is_paginated(client):
    resp = await client.get("/api/v1/competitions", params={"page": 1, "page_size": 2})
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["total"] == 6


async def test_invalid_page_size_is_rejected(client):
    resp = await client.get("/api/v1/competitions", params={"page_size": 1000})
    assert resp.status_code == 422


# Competition id 1 is deterministically "Champions League" and id 2 is
# "Premier League", because the mock provider always syncs COMPETITIONS in
# the same dict order (see mock_data.py) into a freshly emptied schema.


async def test_get_competition_detail(seeded_client):
    resp = await seeded_client.get("/api/v1/competitions/1")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Champions League"


async def test_competition_fixtures(seeded_client):
    resp = await seeded_client.get("/api/v1/competitions/2/fixtures")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4  # epl-1..epl-4 in mock_data.py


async def test_competition_standings_are_ranked(seeded_client):
    resp = await seeded_client.get("/api/v1/competitions/2/standings")
    assert resp.status_code == 200
    rows = resp.json()
    points = [row["points"] for row in rows]
    assert points == sorted(points, reverse=True)


async def test_unknown_competition_returns_404(client):
    resp = await client.get("/api/v1/competitions/99999")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Competition not found"}


async def test_unknown_competition_fixtures_returns_404(client):
    resp = await client.get("/api/v1/competitions/99999/fixtures")
    assert resp.status_code == 404


async def test_unknown_competition_standings_returns_404(client):
    resp = await client.get("/api/v1/competitions/99999/standings")
    assert resp.status_code == 404
