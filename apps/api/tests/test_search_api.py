EMPTY_RESULTS = {"teams": [], "competitions": [], "players": [], "matches": [], "articles": []}


async def test_search_finds_team(client):
    resp = await client.get("/api/v1/search", params={"q": "Arsenal"})
    assert resp.status_code == 200
    assert any(t["name"] == "Arsenal" for t in resp.json()["teams"])


async def test_search_finds_competition(client):
    resp = await client.get("/api/v1/search", params={"q": "Premier"})
    assert any(c["name"] == "Premier League" for c in resp.json()["competitions"])


async def test_search_finds_player(client):
    resp = await client.get("/api/v1/search", params={"q": "Haaland"})
    assert any(p["name"] == "Haaland" for p in resp.json()["players"])


async def test_search_is_case_insensitive(client):
    resp = await client.get("/api/v1/search", params={"q": "arsenal"})
    assert any(t["name"] == "Arsenal" for t in resp.json()["teams"])


async def test_empty_query_returns_empty_lists_not_an_error(client):
    resp = await client.get("/api/v1/search", params={"q": ""})
    assert resp.status_code == 200
    assert resp.json() == EMPTY_RESULTS


async def test_missing_query_param_defaults_to_empty(client):
    resp = await client.get("/api/v1/search")
    assert resp.status_code == 200
    assert resp.json() == EMPTY_RESULTS


async def test_no_matches_returns_empty_lists_not_an_error(client):
    resp = await client.get("/api/v1/search", params={"q": "zzz-nonexistent-zzz"})
    assert resp.status_code == 200
    assert resp.json() == EMPTY_RESULTS
