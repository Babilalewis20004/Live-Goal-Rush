"""Article notifications: opt-in, relevance, caps and idempotency (discovery
§39/§40). Delivery goes through the same device/sender abstraction as match
notifications, tested here with fake senders."""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.article import Article
from app.models.competition import Competition
from app.models.content_notification import ContentNotificationLog
from app.models.device import Device
from app.models.enums import ContentNotificationKind, DevicePlatform, UserRole
from app.models.match import Match
from app.models.team import Team
from app.services import content_notification_service as svc
from app.services.notifications.base import DeliveryResult, NotificationPayload, PushSender
from app.services.notifications.service import NotificationService

API = "/api/v1"


async def _device(session_factory, user_id, token=None):
    async with session_factory() as session:
        session.add(Device(user_id=user_id, platform=DevicePlatform.EXPO_ANDROID, expo_push_token=token or f"ExponentPushToken[{user_id}]"))
        await session.commit()


async def _opt_in(client, headers, *kinds):
    for kind in kinds:
        r = await client.put(f"{API}/notifications/content-preferences", json={"kind": kind, "enabled": True}, headers=headers)
        assert r.status_code == 200, r.text


async def _targets(session_factory, article_id):
    async with session_factory() as session:
        return await svc.resolve_article_targets(session, await session.get(Article, article_id))


# -- preferences ----------------------------------------------------------------------------


async def test_news_kinds_are_off_until_the_user_opts_in(client, make_user):
    _, headers = await make_user("fan@example.com")
    prefs = (await client.get(f"{API}/notifications/content-preferences", headers=headers)).json()
    assert {p["kind"] for p in prefs} == {k.value for k in ContentNotificationKind}
    # News is opt-in; replies to your own comments and editorial updates on your own work default on.
    on_by_default = {"comment_replies", "editorial_updates", "subscription_events"}
    assert all(p["enabled"] is (p["kind"] in on_by_default) and p["default"] is p["enabled"] for p in prefs)

    r = await client.put(f"{API}/notifications/content-preferences", json={"kind": "team_news", "enabled": True}, headers=headers)
    assert r.json() == {"kind": "team_news", "enabled": True, "default": False}
    prefs = {p["kind"]: p["enabled"] for p in (await client.get(f"{API}/notifications/content-preferences", headers=headers)).json()}
    assert prefs["team_news"] is True and prefs["general_news"] is False
    await client.put(f"{API}/notifications/content-preferences", json={"kind": "team_news", "enabled": False}, headers=headers)
    assert next(p for p in (await client.get(f"{API}/notifications/content-preferences", headers=headers)).json() if p["kind"] == "team_news")["enabled"] is False


async def test_preferences_are_private_and_validated(client, make_user):
    assert (await client.get(f"{API}/notifications/content-preferences")).status_code == 401
    assert (await client.put(f"{API}/notifications/content-preferences", json={"kind": "team_news", "enabled": True})).status_code == 401
    _, alice = await make_user("alice@example.com")
    _, bob = await make_user("bob@example.com")
    await _opt_in(client, alice, "team_news")
    assert all(not p["enabled"] for p in (await client.get(f"{API}/notifications/content-preferences", headers=bob)).json() if p["kind"] not in ("comment_replies", "editorial_updates", "subscription_events"))
    assert (await client.put(f"{API}/notifications/content-preferences", json={"kind": "spam", "enabled": True}, headers=alice)).status_code == 422


# -- who gets notified --------------------------------------------------------------------------


async def test_team_news_goes_only_to_opted_in_followers_with_a_device(seeded_client, make_user, publish_article, lookup, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    arsenal = await lookup(Team, "Arsenal")
    fan, fan_h = await make_user("fan@example.com")                      # follows, opted in, device  -> yes
    quiet, quiet_h = await make_user("quiet@example.com")                # follows, device, NOT opted in
    nodev, nodev_h = await make_user("nodevice@example.com")             # follows, opted in, no device
    other, other_h = await make_user("other@example.com")                # opted in + device, not following
    for headers in (fan_h, quiet_h, nodev_h):
        await seeded_client.post(f"{API}/favourites/teams/{arsenal}", headers=headers)
    await _opt_in(seeded_client, fan_h, "team_news")
    await _opt_in(seeded_client, nodev_h, "team_news")
    await _opt_in(seeded_client, other_h, "team_news")
    for u in (fan, quiet, other):
        await _device(session_factory, u.id)

    article = await publish_article(editor, "Arsenal confirm signing", team_ids=[arsenal])
    assert await _targets(session_factory, article["id"]) == {fan.id}
    unrelated = await publish_article(editor, "Nothing about Arsenal")
    assert await _targets(session_factory, unrelated["id"]) == set()


async def test_competition_news_needs_a_followed_competition(seeded_client, make_user, publish_article, lookup, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    pl, laliga = await lookup(Competition, "Premier League"), await lookup(Competition, "LaLiga")
    fan, fan_h = await make_user("fan@example.com")
    await seeded_client.post(f"{API}/favourites/competitions/{pl}", headers=fan_h)
    await _opt_in(seeded_client, fan_h, "competition_news")
    await _device(session_factory, fan.id)
    category = next(c for c in (await seeded_client.get(f"{API}/editor/articles/categories", headers=editor)).json() if c["competition_id"] == pl)

    via_link = await publish_article(editor, "League table shake-up", competition_ids=[pl])
    via_category = await publish_article(editor, "League filed by category", category_id=category["id"])
    other_league = await publish_article(editor, "La Liga news", competition_ids=[laliga])
    assert await _targets(session_factory, via_link["id"]) == {fan.id}
    assert await _targets(session_factory, via_category["id"]) == {fan.id}
    assert await _targets(session_factory, other_league["id"]) == set()


async def test_match_reports_need_the_report_category_and_a_followed_team(seeded_client, make_user, publish_article, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    async with session_factory() as session:
        match = (await session.execute(select(Match).where(Match.provider_id == "epl-1"))).scalar_one()
        match_id, home = match.id, match.home_team_id
    fan, fan_h = await make_user("fan@example.com")
    await seeded_client.post(f"{API}/favourites/teams/{home}", headers=fan_h)
    await _opt_in(seeded_client, fan_h, "match_reports")
    await _device(session_factory, fan.id)
    category = next(c for c in (await seeded_client.get(f"{API}/editor/articles/categories", headers=editor)).json() if c["slug"] == "match-reports")

    report = await publish_article(editor, "Full-time report", match_ids=[match_id], category_id=category["id"])
    plain = await publish_article(editor, "Opinion on the match", match_ids=[match_id])
    assert await _targets(session_factory, report["id"]) == {fan.id}
    assert await _targets(session_factory, plain["id"]) == set()  # linked to the match but not a report


async def test_transfer_and_general_news_are_opt_in_and_general_is_featured_only(seeded_client, make_user, publish_article, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    _, admin = await make_user("root@example.com", UserRole.ADMIN)
    fan, fan_h = await make_user("fan@example.com")
    await _opt_in(seeded_client, fan_h, "transfer_news", "general_news")
    await _device(session_factory, fan.id)
    await seeded_client.get(f"{API}/editor/articles/categories", headers=editor)  # seeds categories
    transfers = next(c for c in (await seeded_client.get(f"{API}/articles/categories")).json() if c["slug"] == "transfers")

    by_category = await publish_article(editor, "Winger joins", category_id=transfers["id"])
    by_tag = await publish_article(editor, "Keeper rumour", tags=["Transfer"])
    ordinary = await publish_article(editor, "Ordinary story")
    featured = await publish_article(editor, "Featured story", is_featured=True)
    assert await _targets(session_factory, by_category["id"]) == {fan.id}
    assert await _targets(session_factory, by_tag["id"]) == {fan.id}
    assert await _targets(session_factory, ordinary["id"]) == set()      # not every article notifies
    assert await _targets(session_factory, featured["id"]) == {fan.id}


async def test_the_daily_cap_limits_how_many_articles_one_user_is_pushed(seeded_client, make_user, publish_article, lookup, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    arsenal = await lookup(Team, "Arsenal")
    fan, fan_h = await make_user("fan@example.com")
    await seeded_client.post(f"{API}/favourites/teams/{arsenal}", headers=fan_h)
    await _opt_in(seeded_client, fan_h, "team_news")
    await _device(session_factory, fan.id)

    articles = [await publish_article(editor, f"Arsenal story {i}", team_ids=[arsenal]) for i in range(settings.content_notification_daily_cap + 1)]
    for article in articles[: settings.content_notification_daily_cap]:
        async with session_factory() as session:
            assert await svc.claim_users(session, article["id"], await svc.resolve_article_targets(session, await session.get(Article, article["id"]))) == {fan.id}
    assert await _targets(session_factory, articles[-1]["id"]) == set()  # cap reached for today


# -- idempotency ----------------------------------------------------------------------------------


async def test_an_article_is_claimed_once_and_each_user_is_claimed_once(seeded_client, make_user, publish_article, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    fan, _ = await make_user("fan@example.com")
    article = await publish_article(editor, "Claim me", is_featured=True)
    async with session_factory() as session:
        first = await svc.claim_article(session, article["id"])
        assert first is not None and first.notified_at is not None
        assert await svc.claim_article(session, article["id"]) is None   # duplicate enqueue / retry
        assert await svc.claim_users(session, article["id"], {fan.id}) == {fan.id}
        assert await svc.claim_users(session, article["id"], {fan.id}) == set()
        assert len((await session.execute(select(ContentNotificationLog))).scalars().all()) == 1


async def test_unpublished_or_draft_articles_cannot_be_claimed(seeded_client, make_user, publish_article, session_factory):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    draft = await publish_article(editor, "Still a draft", publish=False)
    async with session_factory() as session:
        assert await svc.claim_article(session, draft["id"]) is None


async def test_publishing_enqueues_a_notification_job_but_drafts_do_not(client, make_user, publish_article, monkeypatch):
    from app.api.v1 import editor as editor_module

    queued = []
    monkeypatch.setattr(editor_module.dispatch_article_notifications, "delay", lambda article_id: queued.append(article_id))
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    draft = await publish_article(editor, "Draft first", publish=False)
    assert queued == []
    await client.post(f"{API}/editor/articles/{draft['id']}/publish", headers=editor)
    assert queued == [draft["id"]]
    await client.patch(f"{API}/editor/articles/{draft['id']}", json={"excerpt": "edited"}, headers=editor)
    assert queued == [draft["id"]]  # editing a published article does not re-notify


async def test_a_broken_queue_never_breaks_publishing(client, make_user, publish_article, monkeypatch):
    from app.api.v1 import editor as editor_module

    def boom(article_id):
        raise ConnectionError("broker down")

    monkeypatch.setattr(editor_module.dispatch_article_notifications, "delay", boom)
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    article = await publish_article(editor, "Published despite the broker")
    assert article["status"] == "published"


# -- delivery -------------------------------------------------------------------------------------


class _Recorder(PushSender):
    def __init__(self):
        self.sent: list[tuple[int, NotificationPayload]] = []

    async def send(self, device, payload):
        self.sent.append((device.user_id, payload))
        return DeliveryResult(success=True)


async def test_the_push_payload_deep_links_to_the_article_slug(make_user, session_factory):
    fan, _ = await make_user("fan@example.com")
    await _device(session_factory, fan.id)
    recorder = _Recorder()
    async with session_factory() as session:
        service = NotificationService(session)
        service._senders = {DevicePlatform.EXPO_ANDROID: recorder}
        payload = service.build_article_payload("big-signing", "Big signing", "x" * 300)
        await service.send_payload_to_user(fan.id, payload)
    assert recorder.sent[0][0] == fan.id
    sent = recorder.sent[0][1]
    assert sent.data == {"type": "article", "id": "big-signing"}  # the same {type, id} contract as matches
    assert sent.title == "Big signing" and len(sent.body) <= 140


@pytest.mark.parametrize("excerpt", ["short", ""])
async def test_short_excerpts_are_not_truncated(excerpt):
    payload = NotificationService.build_article_payload("s", "T", excerpt)
    assert payload.body == excerpt
