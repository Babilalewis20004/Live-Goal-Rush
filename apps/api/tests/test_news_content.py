"""News/content: authoring workflow, authorization, public visibility,
entity relationships and related articles (discovery §8-16, §28, §44)."""

import pytest
from sqlalchemy import select

from app.models.article import Article
from app.models.competition import Competition
from app.models.enums import UserRole
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team

API = "/api/v1"


async def _team_ids(session_factory, *names):
    async with session_factory() as session:
        return [(await session.execute(select(Team.id).where(Team.name == n))).scalar_one() for n in names]


# -- authorization ------------------------------------------------------------------


async def test_anonymous_cannot_use_the_editor_api(client):
    assert (await client.post(f"{API}/editor/articles", json={"title": "Nope"})).status_code == 401
    assert (await client.get(f"{API}/editor/articles")).status_code == 401


async def test_a_normal_user_gets_403_not_an_editor_view(client, make_user):
    _, headers = await make_user("fan@example.com")
    assert (await client.post(f"{API}/editor/articles", json={"title": "Nope"}, headers=headers)).status_code == 403
    assert (await client.get(f"{API}/editor/articles", headers=headers)).status_code == 403


async def test_editors_only_touch_their_own_articles_admins_touch_all(client, make_user, publish_article):
    _, alice = await make_user("alice@example.com", UserRole.EDITOR)
    _, bob = await make_user("bob@example.com", UserRole.EDITOR)
    _, admin = await make_user("root@example.com", UserRole.ADMIN)
    article = await publish_article(alice, "Alice scoop", publish=False)

    assert (await client.patch(f"{API}/editor/articles/{article['id']}", json={"title": "Hijacked"}, headers=bob)).status_code == 403
    assert (await client.post(f"{API}/editor/articles/{article['id']}/publish", headers=bob)).status_code == 403
    assert (await client.delete(f"{API}/editor/articles/{article['id']}", headers=bob)).status_code == 403
    assert (await client.get(f"{API}/editor/articles/{article['id']}", headers=bob)).status_code == 403

    # Bob's list does not even show Alice's draft; the admin's does.
    assert (await client.get(f"{API}/editor/articles", headers=bob)).json()["total"] == 0
    assert (await client.get(f"{API}/editor/articles", headers=admin)).json()["total"] == 1
    assert (await client.patch(f"{API}/editor/articles/{article['id']}", json={"title": "Admin edit"}, headers=admin)).status_code == 200


async def test_only_admins_create_categories(client, make_user):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    _, admin = await make_user("root@example.com", UserRole.ADMIN)
    body = {"name": "Women's Football"}
    assert (await client.post(f"{API}/editor/articles/categories", json=body, headers=editor)).status_code == 403
    created = await client.post(f"{API}/editor/articles/categories", json=body, headers=admin)
    assert created.status_code == 201 and created.json()["slug"] == "women-s-football"
    assert (await client.post(f"{API}/editor/articles/categories", json=body, headers=admin)).status_code == 422  # duplicate


# -- publishing workflow ---------------------------------------------------------------


async def test_drafts_are_invisible_everywhere_until_published(client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    draft = await publish_article(editor, "Secret transfer plans", publish=False)
    assert draft["status"] == "draft" and draft["published_at"] is None

    assert (await client.get(f"{API}/articles/{draft['slug']}")).status_code == 404
    assert (await client.get(f"{API}/articles")).json()["total"] == 0
    assert (await client.get(f"{API}/search", params={"q": "Secret transfer"})).json()["articles"] == []
    assert (await client.get(f"{API}/articles/{draft['slug']}/related")).status_code == 404

    published = (await client.post(f"{API}/editor/articles/{draft['id']}/publish", headers=editor)).json()
    assert published["status"] == "published" and published["published_at"]
    assert (await client.get(f"{API}/articles/{draft['slug']}")).status_code == 200
    assert (await client.get(f"{API}/articles")).json()["total"] == 1


async def test_unpublish_and_archive_remove_it_from_public_view_immediately(client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    article = await publish_article(editor, "Cup draw reaction")
    # warm every cache that could hold it
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 200
    assert (await client.get(f"{API}/articles")).json()["total"] == 1

    r = await client.post(f"{API}/editor/articles/{article['id']}/unpublish", headers=editor)
    assert r.json()["status"] == "draft"
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 404
    assert (await client.get(f"{API}/articles")).json()["total"] == 0

    await client.post(f"{API}/editor/articles/{article['id']}/publish", headers=editor)
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 200
    r = await client.post(f"{API}/editor/articles/{article['id']}/archive", headers=editor)
    assert r.json()["status"] == "archived"
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 404


async def test_cannot_publish_without_content(client, make_user):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    created = await client.post(f"{API}/editor/articles", json={"title": "Empty one"}, headers=editor)
    assert created.status_code == 201
    r = await client.post(f"{API}/editor/articles/{created.json()['id']}/publish", headers=editor)
    assert r.status_code == 422


async def test_slugs_are_unique_and_stable_across_title_edits(client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    first = await publish_article(editor, "Derby day preview")
    second = await publish_article(editor, "Derby day preview")
    assert first["slug"] == "derby-day-preview" and second["slug"] == "derby-day-preview-2"
    renamed = await client.patch(f"{API}/editor/articles/{first['id']}", json={"title": "A completely new headline"}, headers=editor)
    assert renamed.json()["slug"] == "derby-day-preview"  # URLs do not change


async def test_update_changes_only_the_fields_sent(client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    article = await publish_article(editor, "Original", excerpt="Short summary", tags=["Injury"])
    r = await client.patch(f"{API}/editor/articles/{article['id']}", json={"is_featured": True}, headers=editor)
    body = r.json()
    assert body["is_featured"] is True
    assert body["title"] == "Original" and body["excerpt"] == "Short summary"
    assert [t["slug"] for t in body["tags"]] == ["injury"]


async def test_delete_removes_the_article(client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    article = await publish_article(editor, "Short lived")
    assert (await client.delete(f"{API}/editor/articles/{article['id']}", headers=editor)).status_code == 204
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 404
    assert (await client.get(f"{API}/editor/articles/{article['id']}", headers=editor)).status_code == 404


# -- content safety ------------------------------------------------------------------------


async def test_article_html_is_sanitized_before_it_is_stored(client, make_user, publish_article, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    evil = (
        '<p onclick="steal()">Hello</p><script>alert(1)</script>'
        '<a href="javascript:alert(1)">x</a><img src="https://cdn.example/a.jpg" onerror="alert(2)">'
    )
    article = await publish_article(editor, "XSS attempt", content=evil)
    public = (await client.get(f"{API}/articles/{article['slug']}")).json()
    for needle in ("<script", "onclick", "onerror", "javascript:", "alert("):
        assert needle not in public["content"]
    assert "Hello" in public["content"]
    # and it is the *stored* value that is clean, not just the response
    async with session_factory() as session:
        stored = (await session.execute(select(Article.content).where(Article.id == article["id"]))).scalar_one()
    assert "<script" not in stored and "onclick" not in stored


async def test_featured_image_must_be_http_and_respect_the_host_allow_list(client, make_user, publish_article, monkeypatch):
    from app.core.config import settings

    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    for bad in ("javascript:alert(1)", "data:image/png;base64,AAAA", "/etc/passwd", "ftp://x/y.png", "file:///c:/x.png"):
        r = await client.post(f"{API}/editor/articles", json={"title": "Bad image", "featured_image_url": bad}, headers=editor)
        assert r.status_code == 422, bad

    ok = await publish_article(editor, "Good image", featured_image_url="https://cdn.example/a.jpg")
    assert ok["featured_image_url"] == "https://cdn.example/a.jpg"
    assert ok["featured_image_alt"] == "Good image"  # never missing alt text

    monkeypatch.setattr(settings, "article_image_allowed_hosts", "images.livepitch.example")
    blocked = await client.post(f"{API}/editor/articles", json={"title": "Wrong host", "featured_image_url": "https://evil.example/a.jpg"}, headers=editor)
    assert blocked.status_code == 422
    allowed = await client.post(f"{API}/editor/articles", json={"title": "Right host", "featured_image_url": "https://cdn.images.livepitch.example/a.jpg"}, headers=editor)
    assert allowed.status_code == 201


async def test_public_payload_never_exposes_the_author_email(client, make_user, publish_article):
    user, editor = await make_user("private.address@example.com", UserRole.EDITOR)
    article = await publish_article(editor, "Bylines")
    public = (await client.get(f"{API}/articles/{article['slug']}")).text
    assert "private.address@example.com" not in public
    assert (await client.get(f"{API}/articles/{article['slug']}")).json()["author_name"] == "Private.Address"


# -- categories and tags -----------------------------------------------------------------------


async def test_default_categories_include_one_per_competition(seeded_client, make_user):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    categories = (await seeded_client.get(f"{API}/editor/articles/categories", headers=editor)).json()
    by_slug = {c["slug"]: c for c in categories}
    assert {"football-news", "transfers", "match-reports", "international-football"} <= set(by_slug)
    assert by_slug["premier-league"]["competition_id"] is not None
    assert (await seeded_client.get(f"{API}/articles/categories")).json() == categories  # same list, publicly readable


async def test_tags_are_reusable_and_deduplicated(client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    a = await publish_article(editor, "One", tags=["Real Madrid", "real  madrid", "Transfer"])
    b = await publish_article(editor, "Two", tags=["Real Madrid"])
    assert sorted(t["slug"] for t in a["tags"]) == ["real-madrid", "transfer"]
    assert a["tags"][0]["id"] in {t["id"] for t in a["tags"] + b["tags"]}
    by_tag = (await client.get(f"{API}/articles", params={"tag": "real-madrid"})).json()
    assert by_tag["total"] == 2
    popular = (await client.get(f"{API}/articles/tags")).json()
    assert popular[0]["slug"] == "real-madrid"  # used twice, ranked first
    assert [t["slug"] for t in popular].count("real-madrid") == 1


async def test_category_and_featured_filters_and_pagination(client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    _, admin = await make_user("root@example.com", UserRole.ADMIN)
    cat = (await client.post(f"{API}/editor/articles/categories", json={"name": "Transfers"}, headers=admin)).json()
    for i in range(5):
        await publish_article(editor, f"Story {i}", category_id=cat["id"] if i < 3 else None, is_featured=(i == 0))
    by_cat = (await client.get(f"{API}/articles", params={"category": "transfers"})).json()
    assert by_cat["total"] == 3
    assert (await client.get(f"{API}/articles", params={"featured": True})).json()["total"] == 1

    page1 = (await client.get(f"{API}/articles", params={"page": 1, "page_size": 2})).json()
    page3 = (await client.get(f"{API}/articles", params={"page": 3, "page_size": 2})).json()
    assert (page1["total"], page1["page"], page1["page_size"], len(page1["items"])) == (5, 1, 2, 2)
    assert len(page3["items"]) == 1
    # newest first
    assert page1["items"][0]["title"] == "Story 4"
    assert (await client.get(f"{API}/articles", params={"page_size": 101})).status_code == 422


# -- football entity relationships ---------------------------------------------------------------


async def test_articles_link_to_existing_entities_and_unknown_ids_are_rejected(seeded_client, make_user, publish_article, lookup):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    arsenal = await lookup(Team, "Arsenal")
    haaland = await lookup(Player, "Haaland")
    pl = await lookup(Competition, "Premier League")
    bad = await seeded_client.post(f"{API}/editor/articles", json={"title": "Bad links", "team_ids": [999999]}, headers=editor)
    assert bad.status_code == 422 and "999999" in bad.json()["detail"]

    article = await publish_article(editor, "Linked story", team_ids=[arsenal, arsenal], player_ids=[haaland], competition_ids=[pl])
    detail = (await seeded_client.get(f"{API}/articles/{article['slug']}")).json()
    assert [t["name"] for t in detail["teams"]] == ["Arsenal"]
    assert [p["name"] for p in detail["players"]] == ["Haaland"]
    assert [c["name"] for c in detail["competitions"]] == ["Premier League"]
    assert detail["canonical_path"] == f"/article/{article['slug']}"


async def test_team_player_competition_news_only_contains_linked_articles(seeded_client, make_user, publish_article, lookup):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    arsenal, chelsea = await lookup(Team, "Arsenal"), await lookup(Team, "Chelsea")
    haaland = await lookup(Player, "Haaland")
    pl = await lookup(Competition, "Premier League")
    await publish_article(editor, "Arsenal news", team_ids=[arsenal])
    await publish_article(editor, "Chelsea news", team_ids=[chelsea])
    await publish_article(editor, "Haaland news", player_ids=[haaland])
    await publish_article(editor, "League news", competition_ids=[pl])
    await publish_article(editor, "Unrelated news")

    def titles(resp):
        return sorted(a["title"] for a in resp.json()["items"])

    assert titles(await seeded_client.get(f"{API}/teams/{arsenal}/news")) == ["Arsenal news"]
    assert titles(await seeded_client.get(f"{API}/players/{haaland}/news")) == ["Haaland news"]
    assert titles(await seeded_client.get(f"{API}/competitions/{pl}/news")) == ["League news"]
    # an entity with no news is an empty page, an unknown entity is a 404
    liverpool = await lookup(Team, "Liverpool")
    assert (await seeded_client.get(f"{API}/teams/{liverpool}/news")).json()["items"] == []
    assert (await seeded_client.get(f"{API}/teams/999999/news")).status_code == 404
    assert (await seeded_client.get(f"{API}/players/999999/news")).status_code == 404
    assert (await seeded_client.get(f"{API}/competitions/999999/news")).status_code == 404
    assert (await seeded_client.get(f"{API}/matches/999999/news")).status_code == 404


async def test_competition_news_includes_articles_filed_under_its_category(seeded_client, make_user, publish_article, lookup):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    pl = await lookup(Competition, "Premier League")
    categories = (await seeded_client.get(f"{API}/editor/articles/categories", headers=editor)).json()
    pl_category = next(c for c in categories if c["competition_id"] == pl)
    await publish_article(editor, "Filed under PL", category_id=pl_category["id"])
    news = (await seeded_client.get(f"{API}/competitions/{pl}/news")).json()
    assert [a["title"] for a in news["items"]] == ["Filed under PL"]


async def test_match_news_is_match_then_team_then_competition_and_nothing_else(seeded_client, make_user, publish_article, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    async with session_factory() as session:
        match = (await session.execute(select(Match).where(Match.provider_id == "epl-1"))).scalar_one()
        match_id, home, away, comp = match.id, match.home_team_id, match.away_team_id, match.competition_id
        other_team = (await session.execute(select(Team.id).where(Team.id.notin_([home, away])).limit(1))).scalar_one()
    await publish_article(editor, "Competition piece", competition_ids=[comp])
    await publish_article(editor, "Team piece", team_ids=[home])
    await publish_article(editor, "Match report", match_ids=[match_id])
    await publish_article(editor, "Other club", team_ids=[other_team])
    await publish_article(editor, "Nothing to do with it")

    news = (await seeded_client.get(f"{API}/matches/{match_id}/news")).json()
    assert [(a["title"], a["relation"]) for a in news["items"]] == [
        ("Match report", "match"),
        ("Team piece", "team"),
        ("Competition piece", "competition"),
    ]
    assert news["total"] == 3


# -- related articles ---------------------------------------------------------------------------------


async def test_related_articles_are_scored_deterministically_and_explain_themselves(seeded_client, make_user, publish_article, lookup):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    arsenal, chelsea = await lookup(Team, "Arsenal"), await lookup(Team, "Chelsea")
    pl = await lookup(Competition, "Premier League")
    source = await publish_article(editor, "Source", team_ids=[arsenal], competition_ids=[pl], tags=["Injury"])
    same_team_comp = await publish_article(editor, "Same team and league", team_ids=[arsenal], competition_ids=[pl])
    same_comp = await publish_article(editor, "Same league only", team_ids=[chelsea], competition_ids=[pl])
    same_tag = await publish_article(editor, "Same tag only", tags=["Injury"])
    await publish_article(editor, "Unrelated")
    await publish_article(editor, "Hidden", team_ids=[arsenal], publish=False)

    related = (await seeded_client.get(f"{API}/articles/{source['slug']}/related", params={"limit": 10})).json()
    assert [a["title"] for a in related] == ["Same team and league", "Same league only", "Same tag only"]
    assert related[0]["reason"] == "Same competition, same team"
    assert related[2]["reason"] == "Shared tags"
    assert all(a["slug"] != source["slug"] for a in related)
    assert same_team_comp and same_comp and same_tag  # (created above)


async def test_related_never_returns_an_article_after_it_is_unpublished(client, make_user, publish_article, lookup, seeded_client):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    arsenal = await lookup(Team, "Arsenal")
    a = await publish_article(editor, "Story A", team_ids=[arsenal])
    b = await publish_article(editor, "Story B", team_ids=[arsenal])
    assert [x["title"] for x in (await seeded_client.get(f"{API}/articles/{a['slug']}/related")).json()] == ["Story B"]
    await seeded_client.post(f"{API}/editor/articles/{b['id']}/unpublish", headers=editor)
    assert (await seeded_client.get(f"{API}/articles/{a['slug']}/related")).json() == []


async def test_unknown_article_is_a_404(client):
    assert (await client.get(f"{API}/articles/does-not-exist")).status_code == 404
    assert (await client.get(f"{API}/articles/does-not-exist/related")).status_code == 404


@pytest.mark.parametrize("params", [{"team_id": 0}, {"match_id": -1}, {"category": "x" * 81}])
async def test_list_filters_are_validated(client, params):
    assert (await client.get(f"{API}/articles", params=params)).status_code == 422
