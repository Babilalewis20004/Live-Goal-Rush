"""The personalised feed: deterministic tiers, explanations, privacy and
caching (discovery §6, §7, §29, §36)."""

from datetime import datetime, time, timedelta, timezone

from app.core.redis_keys import RedisKeys
from app.models.competition import Competition
from app.models.enums import UserRole
from app.models.team import Team
from app.services.discovery_service import FEED_TIERS

API = "/api/v1"


async def _follow(client, headers, kind, entity_id):
    r = await client.post(f"{API}/favourites/{kind}/{entity_id}", headers=headers)
    assert r.status_code == 204, r.text


async def _feed(client, headers):
    r = await client.get(f"{API}/feed", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _matches(feed):
    return [i for i in feed["items"] if i["kind"] == "match"]


def _articles(feed):
    return [i for i in feed["items"] if i["kind"] == "article"]


async def test_the_feed_belongs_to_signed_in_users_only(client):
    assert (await client.get(f"{API}/feed")).status_code == 401


async def test_a_user_who_follows_nothing_gets_the_general_feed_and_is_told_so(seeded_client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    _, fan = await make_user("fan@example.com")
    await publish_article(editor, "League news")
    feed = await _feed(seeded_client, fan)
    assert feed["personalised"] is False
    assert [i["article"]["title"] for i in feed["items"]] == ["League news"]
    assert feed["items"][0]["reason"] == "latest"
    assert _matches(feed) == []


async def test_a_followed_team_with_a_live_match_comes_first_with_a_reason(seeded_client, make_user):
    _, fan = await make_user("fan@example.com")
    live = (await seeded_client.get(f"{API}/matches/live")).json()[0]
    team = live["home_team"]
    await _follow(seeded_client, fan, "teams", team["id"])
    feed = await _feed(seeded_client, fan)
    assert feed["personalised"] is True
    top = feed["items"][0]
    assert top["kind"] == "match" and top["match"]["id"] == live["id"]
    assert top["reason"] == "live_followed_match" and top["rank"] == 1
    assert team["name"] in top["explanation"] and "live" in top["explanation"]


async def test_following_a_match_directly_also_counts_as_live_followed(seeded_client, make_user):
    _, fan = await make_user("fan@example.com")
    live = (await seeded_client.get(f"{API}/matches/live")).json()[0]
    await _follow(seeded_client, fan, "matches", live["id"])
    feed = await _feed(seeded_client, fan)
    assert feed["items"][0]["reason"] == "live_followed_match"


async def test_every_match_item_is_in_the_tier_its_state_implies_and_tiers_are_ordered(seeded_client, make_user):
    _, fan = await make_user("fan@example.com")
    for kind in ("teams",):
        for name in ("Liverpool", "Arsenal", "Real Madrid", "Chelsea"):
            team_id = (await seeded_client.get(f"{API}/search", params={"q": name})).json()["teams"][0]["id"]
            await _follow(seeded_client, fan, kind, team_id)
    feed = await _feed(seeded_client, fan)
    items = _matches(feed)
    assert items
    now = datetime.now(timezone.utc)
    day_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    for item in items:
        m = item["match"]
        kickoff = datetime.fromisoformat(m["kickoff_time"])
        if m["status"] in ("live", "halftime"):
            expected = "live_followed_match"
        elif m["status"] == "finished":
            expected = "recent_result"
        elif day_start <= kickoff < day_start + timedelta(days=1):
            expected = "followed_team_today"
        else:
            expected = "followed_team_upcoming"
        assert item["reason"] == expected, (m["status"], m["kickoff_time"])
        assert item["rank"] == FEED_TIERS[expected]
        assert item["explanation"]
    ranks = [i["rank"] for i in feed["items"]]
    assert ranks == sorted(ranks)


async def test_followed_competition_brings_its_matches_but_no_other_leagues(seeded_client, make_user):
    _, fan = await make_user("fan@example.com")
    laliga = (await seeded_client.get(f"{API}/search", params={"q": "LaLiga"})).json()["competitions"]
    competition = laliga[0] if laliga else (await seeded_client.get(f"{API}/search", params={"q": "La Liga"})).json()["competitions"][0]
    await _follow(seeded_client, fan, "competitions", competition["id"])
    feed = await _feed(seeded_client, fan)
    matches = _matches(feed)
    assert matches and all(i["match"]["competition"]["id"] == competition["id"] for i in matches)
    assert all(i["reason"] in {"live_followed_match", "followed_competition_today", "followed_competition_upcoming", "recent_result"} for i in matches)


async def test_news_about_followed_teams_appears_but_other_news_does_not(seeded_client, make_user, publish_article, lookup):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    _, fan = await make_user("fan@example.com")
    arsenal, chelsea = await lookup(Team, "Arsenal"), await lookup(Team, "Chelsea")
    await _follow(seeded_client, fan, "teams", arsenal)
    await publish_article(editor, "Arsenal sign a striker", team_ids=[arsenal])
    await publish_article(editor, "Chelsea sign a keeper", team_ids=[chelsea])
    await publish_article(editor, "Arsenal draft", team_ids=[arsenal], publish=False)
    await publish_article(editor, "General musings")

    feed = await _feed(seeded_client, fan)
    titles = {i["article"]["title"]: i for i in _articles(feed)}
    assert set(titles) == {"Arsenal sign a striker"}
    item = titles["Arsenal sign a striker"]
    assert item["reason"] == "news_followed_team" and item["rank"] == 6
    assert "Arsenal" in item["explanation"]


async def test_news_for_a_followed_competition_includes_its_category(seeded_client, make_user, publish_article, lookup):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    _, fan = await make_user("fan@example.com")
    pl = await lookup(Competition, "Premier League")
    await _follow(seeded_client, fan, "competitions", pl)
    categories = (await seeded_client.get(f"{API}/editor/articles/categories", headers=editor)).json()
    category = next(c for c in categories if c["competition_id"] == pl)
    await publish_article(editor, "Filed under the league", category_id=category["id"])
    await publish_article(editor, "Linked to the league", competition_ids=[pl])
    feed = await _feed(seeded_client, fan)
    reasons = {i["article"]["title"]: i["reason"] for i in _articles(feed)}
    assert reasons == {"Filed under the league": "news_followed_competition", "Linked to the league": "news_followed_competition"}


async def test_old_news_ages_out_of_the_feed(seeded_client, make_user, publish_article, lookup, session_factory):
    from app.models.article import Article

    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    _, fan = await make_user("fan@example.com")
    arsenal = await lookup(Team, "Arsenal")
    await _follow(seeded_client, fan, "teams", arsenal)
    old = await publish_article(editor, "Ancient history", team_ids=[arsenal])
    async with session_factory() as session:
        (await session.get(Article, old["id"])).published_at = datetime.now(timezone.utc) - timedelta(days=30)
        await session.commit()
    assert _articles(await _feed(seeded_client, fan)) == []


async def test_a_recent_search_for_a_team_surfaces_its_news_with_that_reason(seeded_client, make_user, publish_article, lookup):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    _, fan = await make_user("fan@example.com")
    pl = await lookup(Competition, "Premier League")
    await _follow(seeded_client, fan, "competitions", pl)  # makes the feed personalised
    chelsea = await lookup(Team, "Chelsea")
    await publish_article(editor, "Chelsea transfer window", team_ids=[chelsea])
    await seeded_client.post(f"{API}/search/track", json={"query": "Chelsea"}, headers=fan)
    feed = await _feed(seeded_client, fan)
    item = next(i for i in _articles(feed) if i["article"]["title"] == "Chelsea transfer window")
    assert item["reason"] == "news_searched" and item["rank"] == 7


async def test_feeds_are_per_user_and_cached_under_the_users_own_key(seeded_client, make_user, publish_article, lookup, fake_redis):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    alice, a_headers = await make_user("alice@example.com")
    bob, b_headers = await make_user("bob@example.com")
    arsenal, chelsea = await lookup(Team, "Arsenal"), await lookup(Team, "Chelsea")
    await _follow(seeded_client, a_headers, "teams", arsenal)
    await _follow(seeded_client, b_headers, "teams", chelsea)
    await publish_article(editor, "Only for Arsenal fans", team_ids=[arsenal])
    await publish_article(editor, "Only for Chelsea fans", team_ids=[chelsea])

    a_feed = await _feed(seeded_client, a_headers)
    b_feed = await _feed(seeded_client, b_headers)
    assert [i["article"]["title"] for i in _articles(a_feed)] == ["Only for Arsenal fans"]
    assert [i["article"]["title"] for i in _articles(b_feed)] == ["Only for Chelsea fans"]
    assert await fake_redis.get(RedisKeys.user_feed(alice.id)) is not None
    assert await fake_redis.get(RedisKeys.user_feed(bob.id)) is not None
    assert RedisKeys.user_feed(alice.id) != RedisKeys.user_feed(bob.id)
    # a second request is served from cache and still the caller's own
    assert await _feed(seeded_client, a_headers) == a_feed
    # an anonymous caller cannot reach any of it
    assert (await seeded_client.get(f"{API}/feed")).status_code == 401


async def test_following_more_things_changes_the_feed_once_the_short_cache_expires(seeded_client, make_user, lookup, fake_redis):
    user, fan = await make_user("fan@example.com")
    live = (await seeded_client.get(f"{API}/matches/live")).json()[0]
    await _follow(seeded_client, fan, "teams", live["home_team"]["id"])
    before = await _feed(seeded_client, fan)
    await fake_redis.delete(RedisKeys.user_feed(user.id))  # what the TTL does after feed_cache_ttl_seconds
    await _follow(seeded_client, fan, "teams", live["away_team"]["id"])
    after = await _feed(seeded_client, fan)
    assert len(after["items"]) >= len(before["items"])
    assert after["items"][0]["reason"] == "live_followed_match"
