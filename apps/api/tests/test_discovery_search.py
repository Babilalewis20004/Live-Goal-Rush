"""Unified search: grouping, ranking, suggestions, popular/recent searches and
abuse protection (discovery §19-22, §44)."""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.enums import UserRole
from app.models.team import Team

API = "/api/v1"


async def _add_teams(session_factory, *names):
    async with session_factory() as session:
        for i, name in enumerate(names):
            session.add(Team(provider_id=f"rank-{i}-{name}", name=name))
        await session.commit()


# -- grouping ---------------------------------------------------------------------


async def test_results_are_grouped_across_every_entity_type(seeded_client, make_user, publish_article, lookup):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    await publish_article(editor, "Arsenal prepare for Europe")
    body = (await seeded_client.get(f"{API}/search", params={"q": "Arsenal"})).json()
    assert set(body) == {"teams", "competitions", "players", "matches", "articles"}
    assert any(t["name"] == "Arsenal" for t in body["teams"])
    assert body["matches"]  # Arsenal's fixtures
    assert [a["title"] for a in body["articles"]] == ["Arsenal prepare for Europe"]


async def test_competitions_players_and_articles_are_searchable(seeded_client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    await publish_article(editor, "Haaland scores again", excerpt="Another hat-trick")
    assert any(c["name"] == "Premier League" for c in (await seeded_client.get(f"{API}/search", params={"q": "premier"})).json()["competitions"])
    body = (await seeded_client.get(f"{API}/search", params={"q": "Haaland"})).json()
    assert any(p["name"] == "Haaland" for p in body["players"])
    assert len(body["articles"]) == 1
    # an article is also found through its excerpt
    assert len((await seeded_client.get(f"{API}/search", params={"q": "hat-trick"})).json()["articles"]) == 1


async def test_articles_are_found_by_tag(seeded_client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    await publish_article(editor, "Quiet headline", tags=["Injury crisis"])
    body = (await seeded_client.get(f"{API}/search", params={"q": "injury"})).json()
    assert [a["title"] for a in body["articles"]] == ["Quiet headline"]


# -- ranking -----------------------------------------------------------------------


async def test_exact_beats_prefix_beats_contains_beats_fuzzy(client, session_factory):
    await _add_teams(session_factory, "North Arsenal FC", "Arsenal Women", "Arsenal", "Arsnal", "Chelsea")
    names = [t["name"] for t in (await client.get(f"{API}/search", params={"q": "arsenal"})).json()["teams"]]
    assert names[:3] == ["Arsenal", "Arsenal Women", "North Arsenal FC"]
    assert "Chelsea" not in names  # irrelevant records are not returned
    # the near-miss spelling is still found, after the real matches
    assert "Arsnal" in names and names.index("Arsnal") > 2


async def test_a_typo_still_finds_the_team(seeded_client):
    body = (await seeded_client.get(f"{API}/search", params={"q": "Arsnal"})).json()
    assert any(t["name"] == "Arsenal" for t in body["teams"])


async def test_short_queries_are_prefix_only_and_wildcards_are_literal(seeded_client):
    ar = (await seeded_client.get(f"{API}/search", params={"q": "Ar"})).json()["teams"]
    assert ar and all(t["name"].lower().startswith("ar") or (t["short_name"] or "").lower().startswith("ar") for t in ar)
    for wildcard in ("%", "_", "%%", "a%", "\\"):
        assert (await seeded_client.get(f"{API}/search", params={"q": wildcard})).json()["teams"] == [], wildcard


async def test_results_are_capped_per_group(client, session_factory):
    await _add_teams(session_factory, *[f"Rovers {i:02d}" for i in range(30)])
    assert len((await client.get(f"{API}/search", params={"q": "Rovers"})).json()["teams"]) == 10
    assert len((await client.get(f"{API}/search", params={"q": "Rovers", "limit": 3})).json()["teams"]) == 3
    assert (await client.get(f"{API}/search", params={"q": "Rovers", "limit": 21})).status_code == 422


async def test_empty_and_whitespace_queries_return_empty_groups(client):
    for q in ("", "   ", "\t \n"):
        body = (await client.get(f"{API}/search", params={"q": q})).json()
        assert body == {"teams": [], "competitions": [], "players": [], "matches": [], "articles": []}


async def test_no_matches_is_an_empty_not_an_error(client):
    resp = await client.get(f"{API}/search", params={"q": "zzz-nonexistent-zzz"})
    assert resp.status_code == 200 and resp.json()["articles"] == []


# -- abuse protection ----------------------------------------------------------------


async def test_over_long_queries_are_rejected(client):
    assert (await client.get(f"{API}/search", params={"q": "a" * 101})).status_code == 422
    assert (await client.get(f"{API}/search", params={"q": "a" * 100})).status_code == 200
    assert (await client.get(f"{API}/search/suggestions", params={"q": "a" * 101})).status_code == 422


async def test_sql_metacharacters_are_just_text(seeded_client):
    for q in ("'; DROP TABLE teams;--", "\" OR 1=1 --", "Arsenal'); DELETE FROM matches;--"):
        assert (await seeded_client.get(f"{API}/search", params={"q": q})).status_code == 200
    assert (await seeded_client.get(f"{API}/search", params={"q": "Arsenal"})).json()["teams"]  # tables intact


async def test_search_is_rate_limited_per_client(client):
    statuses = [(await client.get(f"{API}/search", params={"q": ""})).status_code for _ in range(settings.search_rate_limit_per_minute + 1)]
    assert statuses[:-1] == [200] * settings.search_rate_limit_per_minute
    assert statuses[-1] == 429


async def test_provider_is_not_queried_for_one_or_two_character_misses(client, monkeypatch):
    from tests.fakes.mock_provider import MockFootballDataProvider

    async def boom(self, query):  # pragma: no cover - must not be called
        raise AssertionError("provider search must not run for short queries")

    monkeypatch.setattr(MockFootballDataProvider, "search", boom)
    assert (await client.get(f"{API}/search", params={"q": "zq"})).status_code == 200


# -- suggestions ----------------------------------------------------------------------------


async def test_suggestions_need_two_characters_and_are_typed(seeded_client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    await publish_article(editor, "Liverpool lift the trophy")
    assert (await seeded_client.get(f"{API}/search/suggestions", params={"q": "L"})).json()["suggestions"] == []
    body = (await seeded_client.get(f"{API}/search/suggestions", params={"q": "Liv"})).json()
    kinds = {s["type"]: s for s in body["suggestions"]}
    assert kinds["team"]["label"] == "Liverpool"
    assert kinds["article"]["slug"] == "liverpool-lift-the-trophy"
    assert len(body["suggestions"]) <= 8
    # prefix matches come before substring matches
    labels = [s["label"] for s in body["suggestions"]]
    assert labels[0].lower().startswith("liv")


async def test_suggestions_are_cached_but_never_include_drafts(seeded_client, make_user, publish_article, fake_redis):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    await publish_article(editor, "Hidden newsworthy draft", publish=False)
    body = (await seeded_client.get(f"{API}/search/suggestions", params={"q": "hidden"})).json()
    assert all(s["type"] != "article" for s in body["suggestions"])
    assert await fake_redis.get("football:search:suggest:hidden") is not None  # cached
    assert (await seeded_client.get(f"{API}/search/suggestions", params={"q": "  HIDDEN "})).json()["suggestions"] == body["suggestions"]


# -- popular searches ----------------------------------------------------------------------------


async def test_popular_searches_need_several_viewers_who_selected_a_result(seeded_client, lookup, monkeypatch):
    monkeypatch.setattr(settings, "popular_search_min_viewers", 2)
    arsenal = await lookup(Team, "Arsenal")
    body = {"query": "Arsenal fixtures", "entity_type": "team", "entity_id": arsenal}

    await seeded_client.post(f"{API}/search/track", json=body, headers={"user-agent": "viewer-1"})
    await seeded_client.post(f"{API}/search/track", json=body, headers={"user-agent": "viewer-1"})  # same viewer again
    assert (await seeded_client.get(f"{API}/search/popular")).json()["queries"] == []  # one viewer is not "popular"

    await seeded_client.post(f"{API}/search/track", json=body, headers={"user-agent": "viewer-2"})
    assert (await seeded_client.get(f"{API}/search/popular")).json()["queries"] == ["arsenal fixtures"]

    # searching without choosing anything never feeds the public list
    await seeded_client.post(f"{API}/search/track", json={"query": "private phrase"}, headers={"user-agent": "viewer-3"})
    await seeded_client.post(f"{API}/search/track", json={"query": "private phrase"}, headers={"user-agent": "viewer-4"})
    assert "private phrase" not in (await seeded_client.get(f"{API}/search/popular")).json()["queries"]


# -- recent searches ------------------------------------------------------------------------------


async def test_recent_searches_require_login_and_are_private(client, make_user):
    assert (await client.get(f"{API}/search/recent")).status_code == 401
    assert (await client.delete(f"{API}/search/recent")).status_code == 401

    _, alice = await make_user("alice@example.com")
    _, bob = await make_user("bob@example.com")
    await client.post(f"{API}/search/track", json={"query": "Alice private query"}, headers=alice)
    assert (await client.get(f"{API}/search/recent", headers=alice)).json()["queries"] == ["Alice private query"]
    assert (await client.get(f"{API}/search/recent", headers=bob)).json()["queries"] == []
    await client.delete(f"{API}/search/recent", headers=bob)  # Bob clearing does not touch Alice
    assert (await client.get(f"{API}/search/recent", headers=alice)).json()["queries"] == ["Alice private query"]


async def test_anonymous_tracking_stores_no_search_history(client, session_factory):
    from app.models.engagement import RecentSearch

    assert (await client.post(f"{API}/search/track", json={"query": "anonymous query"})).status_code == 204
    async with session_factory() as session:
        assert (await session.execute(select(RecentSearch))).first() is None


async def test_recent_searches_are_newest_first_unique_and_capped(client, make_user):
    _, headers = await make_user("fan@example.com")
    for i in range(12):
        await client.post(f"{API}/search/track", json={"query": f"query {i:02d}"}, headers=headers)
    await client.post(f"{API}/search/track", json={"query": "QUERY 05"}, headers=headers)  # case-insensitive repeat moves to front
    recent = (await client.get(f"{API}/search/recent", headers=headers)).json()["queries"]
    assert len(recent) == 10
    assert recent[0] == "QUERY 05" and "query 05" not in recent
    assert recent[1] == "query 11"
    assert "query 00" not in recent and "query 01" not in recent


async def test_recent_searches_can_be_removed_one_by_one_or_cleared(client, make_user):
    _, headers = await make_user("fan@example.com")
    for q in ("one", "two", "three"):
        await client.post(f"{API}/search/track", json={"query": q}, headers=headers)
    await client.delete(f"{API}/search/recent", params={"query": "TWO"}, headers=headers)
    assert (await client.get(f"{API}/search/recent", headers=headers)).json()["queries"] == ["three", "one"]
    await client.delete(f"{API}/search/recent", headers=headers)
    assert (await client.get(f"{API}/search/recent", headers=headers)).json()["queries"] == []


@pytest.mark.parametrize("body", [{"query": ""}, {"query": "x" * 101}, {"query": "ok", "entity_type": "nonsense"}, {"query": "ok", "entity_type": "team", "entity_id": 0}])
async def test_track_validates_its_input(client, body):
    assert (await client.post(f"{API}/search/track", json=body)).status_code == 422


async def test_tracking_a_made_up_entity_counts_nothing(client, fake_redis):
    body = {"query": "ghost", "entity_type": "team", "entity_id": 987654}
    assert (await client.post(f"{API}/search/track", json=body)).status_code == 204
    assert [k async for k in fake_redis.raw.scan_iter(match="football:engagement:*")] == []
