"""View tracking, aggregation, trending and the discovery home (discovery
§23-27, §36)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.redis_keys import RedisKeys
from app.models.article import Article
from app.models.competition import Competition
from app.models.engagement import EngagementBucket
from app.models.enums import UserRole
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.services.discovery_service import refresh_trending
from app.services.engagement_service import (
    aggregate_engagement,
    compute_trending,
    record_engagement,
    viewer_fingerprint,
)

API = "/api/v1"


def _hours_ago(h: float) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(hours=h)).replace(minute=0, second=0, microsecond=0)


async def _bucket(session_factory, entity, entity_id, hours_ago, count, signal="view"):
    async with session_factory() as session:
        session.add(EngagementBucket(entity_type=entity, entity_id=entity_id, signal=signal, bucket=_hours_ago(hours_ago), count=count))
        await session.commit()


# -- recording & de-duplication ---------------------------------------------------------


async def test_the_same_viewer_refreshing_counts_once(fake_redis):
    raw = fake_redis.raw
    assert await record_engagement(raw, "team", 7, "view", "viewer-a") is True
    for _ in range(5):
        assert await record_engagement(raw, "team", 7, "view", "viewer-a") is False  # refresh spam
    assert await record_engagement(raw, "team", 7, "view", "viewer-b") is True
    assert await record_engagement(raw, "player", 7, "view", "viewer-a") is True  # a different thing
    [key] = [k async for k in raw.scan_iter(match="football:engagement:counts:*")]
    assert await raw.hgetall(key) == {"team:7:view": "2", "player:7:view": "1"}


async def test_fingerprints_are_stable_keyed_and_not_the_raw_address():
    a = viewer_fingerprint("203.0.113.9", "Mozilla/5.0")
    assert a == viewer_fingerprint("203.0.113.9", "Mozilla/5.0")
    assert a != viewer_fingerprint("203.0.113.10", "Mozilla/5.0")
    assert "203.0.113.9" not in a


async def test_recording_survives_redis_being_down():
    class Broken:
        async def set(self, *a, **k):
            raise ConnectionError("down")

    assert await record_engagement(Broken(), "team", 1, "view", "v") is False  # no exception


async def test_view_endpoint_counts_real_things_once(seeded_client, lookup, fake_redis):
    arsenal = await lookup(Team, "Arsenal")
    body = {"entity_type": "team", "entity_id": arsenal}
    for _ in range(3):
        assert (await seeded_client.post(f"{API}/engagement/view", json=body)).status_code == 204
    [key] = [k async for k in fake_redis.raw.scan_iter(match="football:engagement:counts:*")]
    assert await fake_redis.raw.hgetall(key) == {f"team:{arsenal}:view": "1"}


async def test_view_endpoint_rejects_unknown_and_unpublished_entities(seeded_client, make_user, publish_article, fake_redis):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    draft = await publish_article(editor, "Not public yet", publish=False)
    assert (await seeded_client.post(f"{API}/engagement/view", json={"entity_type": "team", "entity_id": 999999})).status_code == 404
    assert (await seeded_client.post(f"{API}/engagement/view", json={"entity_type": "article", "entity_id": draft["id"]})).status_code == 404
    assert (await seeded_client.post(f"{API}/engagement/view", json={"entity_type": "article", "slug": draft["slug"]})).status_code == 404
    assert (await seeded_client.post(f"{API}/engagement/view", json={"entity_type": "nonsense", "entity_id": 1})).status_code == 422
    assert [k async for k in fake_redis.raw.scan_iter(match="football:engagement:counts:*")] == []


async def test_articles_can_be_tracked_by_slug(seeded_client, make_user, publish_article, fake_redis):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    article = await publish_article(editor, "Tracked by slug")
    r = await seeded_client.post(f"{API}/engagement/view", json={"entity_type": "article", "slug": article["slug"]})
    assert r.status_code == 204
    [key] = [k async for k in fake_redis.raw.scan_iter(match="football:engagement:counts:*")]
    assert await fake_redis.raw.hgetall(key) == {f"article:{article['id']}:view": "1"}


# -- aggregation ---------------------------------------------------------------------------


async def test_aggregation_moves_redis_counts_into_postgres_exactly_once(seeded_client, make_user, publish_article, fake_redis, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    article = await publish_article(editor, "Counted article")
    for viewer in ("a", "b", "c"):
        await record_engagement(fake_redis.raw, "article", article["id"], "view", viewer)

    async with session_factory() as session:
        assert await aggregate_engagement(fake_redis.raw, session) == 1
        rows = (await session.execute(select(EngagementBucket))).scalars().all()
        assert [(r.entity_type, r.entity_id, r.signal, r.count) for r in rows] == [("article", article["id"], "view", 3)]
        assert (await session.execute(select(Article.view_count).where(Article.id == article["id"]))).scalar_one() == 3

    # nothing left in Redis, so a second run adds nothing
    assert [k async for k in fake_redis.raw.scan_iter(match="football:engagement:*counts*")] == []
    async with session_factory() as session:
        assert await aggregate_engagement(fake_redis.raw, session) == 0
        assert (await session.execute(select(Article.view_count).where(Article.id == article["id"]))).scalar_one() == 3

    # new traffic in the same hour accumulates onto the same bucket row
    await record_engagement(fake_redis.raw, "article", article["id"], "view", "d")
    async with session_factory() as session:
        await aggregate_engagement(fake_redis.raw, session)
        assert (await session.execute(select(EngagementBucket.count))).scalar_one() == 4
        assert (await session.execute(select(Article.view_count).where(Article.id == article["id"]))).scalar_one() == 4


async def test_aggregation_ignores_garbage_and_purges_old_buckets(fake_redis, session_factory):
    key = RedisKeys.engagement_counts(int(datetime.now(timezone.utc).timestamp()) // 3600 * 3600)
    await fake_redis.raw.hset(key, mapping={"team:1": "5", "team:x:view": "5", "bogus:1:view": "5", "team:1:view": "-3", "team:1:search": "oops"})
    async with session_factory() as session:
        session.add(EngagementBucket(entity_type="team", entity_id=1, signal="view", bucket=datetime.now(timezone.utc) - timedelta(days=90), count=9))
        await session.commit()
        assert await aggregate_engagement(fake_redis.raw, session) == 0
        assert (await session.execute(select(EngagementBucket))).first() is None  # garbage skipped, 90-day-old row purged


# -- trending -----------------------------------------------------------------------------------


async def test_no_data_means_no_ranking(client, session_factory):
    async with session_factory() as session:
        for kind in ("team", "player", "competition", "article"):
            assert await compute_trending(session, kind) == []
    body = (await client.get(f"{API}/discovery/trending")).json()
    assert body["teams"] == body["players"] == body["competitions"] == body["articles"] == []


async def test_more_attention_ranks_higher_and_unvisited_entities_are_absent(seeded_client, lookup, session_factory):
    arsenal, chelsea, spurs = await lookup(Team, "Arsenal"), await lookup(Team, "Chelsea"), await lookup(Team, "Tottenham Hotspur")
    await _bucket(session_factory, "team", arsenal, 1, 10)
    await _bucket(session_factory, "team", chelsea, 1, 3)
    async with session_factory() as session:
        ranked = await compute_trending(session, "team")
    ids = [s.id for s in ranked if s.signals.get("views")]
    assert ids == [arsenal, chelsea]
    assert spurs not in [s.id for s in ranked if not s.signals.get("live_matches")]
    assert ranked[0].signals["views"] == 10


async def test_window_excludes_old_activity(seeded_client, lookup, session_factory):
    arsenal = await lookup(Team, "Arsenal")
    await _bucket(session_factory, "team", arsenal, 30, 50)
    async with session_factory() as session:
        assert [s for s in await compute_trending(session, "team", 24) if s.signals.get("views")] == []
        assert [s.id for s in await compute_trending(session, "team", 48) if s.signals.get("views")] == [arsenal]


async def test_recent_activity_outranks_the_same_amount_long_ago(seeded_client, lookup, session_factory):
    arsenal, chelsea = await lookup(Team, "Arsenal"), await lookup(Team, "Chelsea")
    await _bucket(session_factory, "team", arsenal, 20, 8)
    await _bucket(session_factory, "team", chelsea, 1, 8)
    async with session_factory() as session:
        ranked = [s.id for s in await compute_trending(session, "team") if s.signals.get("views")]
    assert ranked == [chelsea, arsenal]


async def test_a_chosen_search_result_counts_more_than_a_page_view(seeded_client, lookup, session_factory):
    arsenal, chelsea = await lookup(Team, "Arsenal"), await lookup(Team, "Chelsea")
    await _bucket(session_factory, "team", arsenal, 1, 5, "view")
    await _bucket(session_factory, "team", chelsea, 1, 3, "search")
    async with session_factory() as session:
        ranked = [s for s in await compute_trending(session, "team") if s.signals]
    first = ranked[0]
    # (Chelsea is also in a live fixture, which is its own separate signal)
    assert first.id == chelsea and first.signals["searches"] == 3 and "views" not in first.signals


async def test_match_views_lend_attention_to_both_teams(seeded_client, session_factory):
    async with session_factory() as session:
        match = (await session.execute(select(Match).where(Match.provider_id == "epl-4"))).scalar_one()
        home, away = match.home_team_id, match.away_team_id
    await _bucket(session_factory, "match", match.id, 1, 20)
    async with session_factory() as session:
        ranked = {s.id: s for s in await compute_trending(session, "team")}
    assert ranked[home].signals["match_views"] == 20 and ranked[away].signals["match_views"] == 20


async def test_live_matches_make_their_teams_and_competitions_trend(seeded_client):
    live = (await seeded_client.get(f"{API}/matches/live")).json()
    assert live, "the mock provider always has live fixtures"
    body = (await seeded_client.get(f"{API}/discovery/trending")).json()
    team_ids = {t["item"]["id"] for t in body["teams"]}
    assert {live[0]["home_team"]["id"], live[0]["away_team"]["id"]} <= team_ids
    entry = next(t for t in body["teams"] if t["item"]["id"] == live[0]["home_team"]["id"])
    assert entry["signals"]["live_matches"] >= 1 and entry["score"] > 0
    assert live[0]["competition"]["id"] in {c["item"]["id"] for c in body["competitions"]}


async def test_trending_articles_decay_with_age_and_exclude_unpublished(seeded_client, make_user, publish_article, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    fresh = await publish_article(editor, "Fresh story")
    old = await publish_article(editor, "Old story")
    unviewed = await publish_article(editor, "Nobody read this")
    draft = await publish_article(editor, "Draft story", publish=False)
    async with session_factory() as session:
        article = await session.get(Article, old["id"])
        article.published_at = datetime.now(timezone.utc) - timedelta(days=10)
        await session.commit()
    for a in (fresh, old, draft):
        await _bucket(session_factory, "article", a["id"], 1, 6)

    async with session_factory() as session:
        ranked = [s.id for s in await compute_trending(session, "article")]
    assert ranked[0] == fresh["id"]
    body = (await seeded_client.get(f"{API}/discovery/trending/articles")).json()
    titles = [t["item"]["title"] for t in body]
    assert "Fresh story" in titles and "Draft story" not in titles and "Nobody read this" not in titles
    assert unviewed["id"] not in ranked


async def test_trending_players_come_from_recent_news(seeded_client, make_user, publish_article, lookup):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    haaland = await lookup(Player, "Haaland")
    await publish_article(editor, "Haaland special", player_ids=[haaland])
    body = (await seeded_client.get(f"{API}/discovery/trending/players")).json()
    assert [t["item"]["name"] for t in body] == ["Haaland"]
    assert body[0]["signals"] == {"news": 1}


async def test_trending_endpoint_validates_and_caches(seeded_client, lookup, session_factory, fake_redis):
    arsenal = await lookup(Team, "Arsenal")
    await _bucket(session_factory, "team", arsenal, 1, 4)
    first = (await seeded_client.get(f"{API}/discovery/trending/teams", params={"limit": 30})).json()
    assert any(t["item"]["id"] == arsenal for t in first)
    cached = await fake_redis.get(RedisKeys.trending("team", settings.trending_window_hours))
    assert cached and any(c["id"] == arsenal for c in cached)

    # served from the cache: new raw data does not change the answer until a refresh
    await _bucket(session_factory, "team", await lookup(Team, "Chelsea"), 1, 500)
    assert (await seeded_client.get(f"{API}/discovery/trending/teams", params={"limit": 30})).json() == first
    async with session_factory() as session:
        counts = await refresh_trending(session, fake_redis)
    assert set(counts) == {"team", "player", "competition", "article"}
    refreshed = (await seeded_client.get(f"{API}/discovery/trending/teams", params={"limit": 30})).json()
    assert refreshed[0]["item"]["name"] == "Chelsea"

    assert (await seeded_client.get(f"{API}/discovery/trending/goalkeepers")).status_code == 404
    assert (await seeded_client.get(f"{API}/discovery/trending", params={"window_hours": 0})).status_code == 422
    assert (await seeded_client.get(f"{API}/discovery/trending", params={"limit": 31})).status_code == 422


# -- home -------------------------------------------------------------------------------------------


async def test_home_has_every_section_even_when_there_is_no_content(client):
    body = (await client.get(f"{API}/discovery/home")).json()
    assert set(body) >= {
        "latest_results", "featured_articles", "latest_articles", "trending_teams",
        "trending_players", "trending_articles", "popular_competitions", "generated_at",
    }
    assert body["latest_articles"] == [] and body["trending_articles"] == []


async def test_home_shows_results_news_and_busy_competitions(seeded_client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    await publish_article(editor, "Big headline", is_featured=True)
    body = (await seeded_client.get(f"{API}/discovery/home")).json()
    assert all(m["status"] == "finished" for m in body["latest_results"]) and body["latest_results"]
    assert [a["title"] for a in body["featured_articles"]] == ["Big headline"]
    assert [a["title"] for a in body["latest_articles"]] == ["Big headline"]
    assert body["popular_competitions"]  # falls back to the busiest competitions by fixtures


async def test_home_is_cached_and_invalidated_when_content_changes(seeded_client, make_user, publish_article, fake_redis):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    assert (await seeded_client.get(f"{API}/discovery/home")).json()["latest_articles"] == []
    assert [k async for k in fake_redis.raw.scan_iter(match="football:discovery:home:*")]
    article = await publish_article(editor, "Breaking news")
    assert [a["title"] for a in (await seeded_client.get(f"{API}/discovery/home")).json()["latest_articles"]] == ["Breaking news"]
    await seeded_client.post(f"{API}/editor/articles/{article['id']}/unpublish", headers=editor)
    assert (await seeded_client.get(f"{API}/discovery/home")).json()["latest_articles"] == []


async def test_public_pages_survive_a_dead_cache(seeded_client, monkeypatch, fake_redis):
    async def boom(*a, **k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fake_redis.raw, "get", boom)
    monkeypatch.setattr(fake_redis, "get", boom)
    assert (await seeded_client.get(f"{API}/discovery/home")).status_code == 200
    assert (await seeded_client.get(f"{API}/articles")).status_code == 200


async def test_competition_names_are_real_rows(seeded_client, lookup):
    # sanity for the fixtures the tests above lean on
    assert await lookup(Competition, "Premier League")
