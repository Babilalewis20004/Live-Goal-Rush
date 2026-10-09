"""One continuous discovery scenario (the Phase 5 end-to-end walk-through),
using the real HTTP API, the real Redis-backed tracking/aggregation/trending
code, and the real notification claim/dispatch services (only the push network
call is replaced by a recorder)."""

from sqlalchemy import select

from app.models.article import Article
from app.models.competition import Competition
from app.models.device import Device
from app.models.enums import DevicePlatform, UserRole
from app.models.team import Team
from app.services import content_notification_service as content
from app.services.discovery_service import refresh_trending
from app.services.engagement_service import aggregate_engagement
from app.services.notifications.base import DeliveryResult, PushSender
from app.services.notifications.service import NotificationService

API = "/api/v1"


class _Recorder(PushSender):
    def __init__(self):
        self.sent = []

    async def send(self, device, payload):
        self.sent.append((device.user_id, payload))
        return DeliveryResult(success=True)


async def _notify(session_factory, article_id, recorder):
    """What `dispatch_article_notifications` does, minus the Celery wrapper."""
    async with session_factory() as session:
        article = await content.claim_article(session, article_id)
        if article is None:
            return
        users = await content.claim_users(session, article.id, await content.resolve_article_targets(session, article))
        service = NotificationService(session)
        service._senders = {DevicePlatform.EXPO_ANDROID: recorder}
        payload = service.build_article_payload(article.slug, article.title, article.excerpt)
        for user_id in users:
            await service.send_payload_to_user(user_id, payload)


async def test_phase5_discovery_end_to_end(seeded_client, make_user, lookup, session_factory, fake_redis):
    client = seeded_client
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    arsenal, premier_league = await lookup(Team, "Arsenal"), await lookup(Competition, "Premier League")

    # 1. Create / log in a user (real registration endpoint).
    reg = await client.post(
        f"{API}/auth/register",
        json={"email": "fan@example.com", "password": "Sup3rSecret!", "password_confirm": "Sup3rSecret!", "display_name": "Fan"},
    )
    assert reg.status_code in (200, 201), reg.text
    me = (await client.get(f"{API}/users/me")).json()
    async with session_factory() as session:
        session.add(Device(user_id=me["id"], platform=DevicePlatform.EXPO_ANDROID, expo_push_token="ExponentPushToken[fan]"))
        await session.commit()

    # 2. Follow Team A and Competition B.
    assert (await client.post(f"{API}/favourites/teams/{arsenal}")).status_code == 204
    assert (await client.post(f"{API}/favourites/competitions/{premier_league}")).status_code == 204

    # 3-5. Search for Team A: it is returned, the user picks it.
    found = (await client.get(f"{API}/search", params={"q": "Arsenal"})).json()
    assert found["teams"][0]["id"] == arsenal
    assert (await client.post(f"{API}/search/track", json={"query": "Arsenal", "entity_type": "team", "entity_id": arsenal})).status_code == 204
    assert (await client.get(f"{API}/search/recent")).json()["queries"] == ["Arsenal"]

    # 6. Open Team A: fixtures and results load, and there is no news yet.
    assert (await client.get(f"{API}/teams/{arsenal}")).status_code == 200
    assert (await client.get(f"{API}/teams/{arsenal}/fixtures")).status_code == 200
    assert (await client.get(f"{API}/teams/{arsenal}/results")).status_code == 200
    assert (await client.get(f"{API}/teams/{arsenal}/news")).json()["items"] == []
    before = (await client.get(f"{API}/feed")).json()
    assert before["personalised"] is True and not [i for i in before["items"] if i["kind"] == "article"]

    # The user opts in to team news (they would otherwise get nothing).
    assert (await client.put(f"{API}/notifications/content-preferences", json={"kind": "team_news", "enabled": True})).status_code == 200

    # 7. An editor writes and publishes an article about Team A in Competition B.
    draft = await client.post(
        f"{API}/editor/articles",
        headers=editor,
        json={
            "title": "Arsenal edge a thriller",
            "excerpt": "A late goal settles it.",
            "content": "<h2>Match report</h2><p>Arsenal won <script>alert(1)</script>late.</p>",
            "team_ids": [arsenal],
            "competition_ids": [premier_league],
            "tags": ["Match Report"],
        },
    )
    assert draft.status_code == 201
    article = draft.json()
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 404  # still a draft
    published = await client.post(f"{API}/editor/articles/{article['id']}/publish", headers=editor)
    assert published.json()["status"] == "published"
    second = await client.post(
        f"{API}/editor/articles",
        headers=editor,
        json={"title": "Arsenal injury update", "content": "<p>Latest on the squad.</p>", "team_ids": [arsenal], "status": "published"},
    )
    assert second.status_code == 201

    # 8-9. It shows up in Team A's news, in the latest news, and (once the
    #      short per-user cache window passes) in the user's feed.
    team_news = (await client.get(f"{API}/teams/{arsenal}/news")).json()
    assert {a["title"] for a in team_news["items"]} == {"Arsenal edge a thriller", "Arsenal injury update"}
    assert (await client.get(f"{API}/articles")).json()["total"] == 2
    assert [a["title"] for a in (await client.get(f"{API}/competitions/{premier_league}/news")).json()["items"]] == ["Arsenal edge a thriller"]
    await fake_redis.delete(f"football:feed:user:{me['id']}")
    after = (await client.get(f"{API}/feed")).json()
    news_items = [i for i in after["items"] if i["kind"] == "article"]
    assert {i["article"]["title"] for i in news_items} == {"Arsenal edge a thriller", "Arsenal injury update"}
    assert all(i["reason"] == "news_followed_team" for i in news_items)

    # 10. The user opens the article: sanitized body, related content, linked entities.
    detail = (await client.get(f"{API}/articles/{article['slug']}")).json()
    assert "<script" not in detail["content"] and "Arsenal won" in detail["content"]
    assert [t["name"] for t in detail["teams"]] == ["Arsenal"] and detail["canonical_path"] == f"/article/{article['slug']}"
    related = (await client.get(f"{API}/articles/{article['slug']}/related")).json()
    assert [a["title"] for a in related] == ["Arsenal injury update"] and "same team" in related[0]["reason"].lower()

    # 11-12. The view is tracked, aggregated, and popularity updates.
    for entity in ({"entity_type": "article", "slug": article["slug"]}, {"entity_type": "team", "entity_id": arsenal}):
        assert (await client.post(f"{API}/engagement/view", json=entity)).status_code == 204
    async with session_factory() as session:
        assert await aggregate_engagement(fake_redis.raw, session) == 3  # article view, team view, team search
        assert (await session.execute(select(Article.view_count).where(Article.id == article["id"]))).scalar_one() == 1
        await refresh_trending(session, fake_redis)
    trending_articles = (await client.get(f"{API}/discovery/trending/articles")).json()
    assert [t["item"]["slug"] for t in trending_articles] == [article["slug"]]
    assert trending_articles[0]["signals"] == {"views": 1}
    trending_teams = (await client.get(f"{API}/discovery/trending/teams", params={"limit": 30})).json()
    arsenal_entry = next(t for t in trending_teams if t["item"]["id"] == arsenal)
    assert arsenal_entry["signals"]["views"] == 1 and arsenal_entry["signals"]["searches"] == 1 and arsenal_entry["signals"]["news"] == 2

    # 13-14. A notification is delivered only because the preference allows it,
    #        and its deep link opens the article.
    recorder = _Recorder()
    await _notify(session_factory, article["id"], recorder)
    assert [(uid, p.data) for uid, p in recorder.sent] == [(me["id"], {"type": "article", "id": article["slug"]})]
    await _notify(session_factory, article["id"], recorder)  # a duplicate dispatch sends nothing
    assert len(recorder.sent) == 1

    await client.put(f"{API}/notifications/content-preferences", json={"kind": "team_news", "enabled": False})
    muted = _Recorder()
    await _notify(session_factory, second.json()["id"], muted)
    assert muted.sent == []

    # 15. An anonymous visitor can still read everything public, and nothing private.
    client.cookies.clear()
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 200
    assert (await client.get(f"{API}/articles")).json()["total"] == 2
    assert (await client.get(f"{API}/discovery/home")).status_code == 200
    assert (await client.get(f"{API}/feed")).status_code == 401
    assert (await client.get(f"{API}/search/recent")).status_code == 401
    assert (await client.get(f"{API}/notifications/content-preferences")).status_code == 401
