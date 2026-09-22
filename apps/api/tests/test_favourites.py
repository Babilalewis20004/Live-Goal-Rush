"""Favourites tests (Phase 3 §31): add/remove/duplicate/list, cross-user
isolation, and cascade-on-delete. Uses `seeded_client` (pre-populated via
the mock provider) so real team/competition/match ids exist -- team 1 is
Real Madrid, per the id-mapping comment in `test_teams_api.py`.
"""

from sqlalchemy import select

from app.models.favourite import FavouriteTeam
from app.models.team import Team


async def _login_cookies(seeded_client, email, password="Sup3rSecret!"):
    resp = await seeded_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "password_confirm": password},
    )
    assert resp.status_code == 201
    return resp.cookies


async def test_follow_and_list_team(seeded_client):
    await _login_cookies(seeded_client, "fan@example.com")
    follow_resp = await seeded_client.post("/api/v1/favourites/teams/1")
    assert follow_resp.status_code == 204

    list_resp = await seeded_client.get("/api/v1/favourites")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert len(body["teams"]) == 1
    assert body["teams"][0]["team"]["id"] == 1
    assert body["teams"][0]["team"]["name"] == "Real Madrid"


async def test_unfollow_team(seeded_client):
    await _login_cookies(seeded_client, "fan2@example.com")
    await seeded_client.post("/api/v1/favourites/teams/1")
    unfollow_resp = await seeded_client.delete("/api/v1/favourites/teams/1")
    assert unfollow_resp.status_code == 204

    list_resp = await seeded_client.get("/api/v1/favourites")
    assert list_resp.json()["teams"] == []


async def test_duplicate_follow_is_idempotent(seeded_client):
    await _login_cookies(seeded_client, "fan3@example.com")
    first = await seeded_client.post("/api/v1/favourites/teams/1")
    second = await seeded_client.post("/api/v1/favourites/teams/1")
    assert first.status_code == 204
    assert second.status_code == 204

    list_resp = await seeded_client.get("/api/v1/favourites")
    assert len(list_resp.json()["teams"]) == 1


async def test_follow_unknown_team_returns_404(seeded_client):
    await _login_cookies(seeded_client, "fan4@example.com")
    resp = await seeded_client.post("/api/v1/favourites/teams/99999")
    assert resp.status_code == 404


async def test_favourites_requires_authentication(seeded_client):
    resp = await seeded_client.get("/api/v1/favourites")
    assert resp.status_code == 401


async def test_favourite_competition_and_match(seeded_client):
    await _login_cookies(seeded_client, "fan5@example.com")

    comp_resp = await seeded_client.get("/api/v1/competitions/1")
    assert comp_resp.status_code == 200

    follow_comp = await seeded_client.post("/api/v1/favourites/competitions/1")
    assert follow_comp.status_code == 204

    follow_match = await seeded_client.post("/api/v1/favourites/matches/1")
    assert follow_match.status_code == 204

    list_resp = await seeded_client.get("/api/v1/favourites")
    body = list_resp.json()
    assert len(body["competitions"]) == 1
    assert len(body["matches"]) == 1
    assert body["matches"][0]["match"]["id"] == 1


async def test_cross_user_isolation(seeded_client):
    await _login_cookies(seeded_client, "userA@example.com")
    await seeded_client.post("/api/v1/favourites/teams/1")

    # Same shared AsyncClient's cookie jar now holds user A's cookies --
    # logging in as user B overwrites them, simulating a second user.
    await _login_cookies(seeded_client, "userB@example.com")
    b_list = await seeded_client.get("/api/v1/favourites")
    assert b_list.json()["teams"] == []

    # User B unfollowing team 1 (which only A follows) must not affect A.
    unfollow_resp = await seeded_client.delete("/api/v1/favourites/teams/1")
    assert unfollow_resp.status_code == 204


async def test_favourite_team_cascades_on_team_delete(test_user, test_engine):
    """Verifies the `ondelete="CASCADE"` constraint itself, using a
    standalone team with no fixtures -- team 1 from `seeded_client` is
    referenced by `matches.home_team_id`/`away_team_id` (a plain,
    non-cascading FK, Phase 1's own constraint), so deleting it would fail
    for an unrelated reason before this constraint was even exercised."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        team = Team(provider_id="standalone-1", name="Standalone FC")
        session.add(team)
        await session.flush()
        session.add(FavouriteTeam(user_id=test_user.id, team_id=team.id))
        await session.commit()
        team_id = team.id

        await session.delete(team)
        await session.commit()

        remaining = await session.execute(select(FavouriteTeam).where(FavouriteTeam.team_id == team_id))
        assert remaining.scalars().all() == []
