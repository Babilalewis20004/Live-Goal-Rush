"""Moderation extras, new reactions, community-aware feed, persisted/personal insights,
Phase 6b notifications and real-time routing."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.core.redis_keys import RedisKeys
from app.events.schemas import RealtimeEventType
from app.models.analytics import InsightRecord
from app.models.community import Poll, PollOption, ProfileReport, SocialNotificationLog
from app.models.device import Device
from app.models.enums import (
    ContentNotificationKind,
    DevicePlatform,
    InsightEntityType,
    MatchStatus,
    PollKind,
    PollStatus,
    UserRole,
)
from app.models.favourite import FavouriteTeam
from app.models.match import Match
from app.models.statistics import MatchStatistic
from app.models.user import User
from app.services import personal_insights
from app.services.insight_records import InsightGenerator, live_insights
from app.services.notifications.base import DeliveryResult, PushSender
from app.services.notifications.service import NotificationService
from app.websocket.pubsub_bridge import PubSubBridge
from tests.football_data import NOW, add_player_stats, history, make_competition, make_match, make_player, make_team

API = "/api/v1"


class Recorder(PushSender):
    def __init__(self):
        self.sent = []

    async def send(self, device, payload):
        self.sent.append((device.user_id, payload))
        return DeliveryResult(success=True)


async def notifier(session):
    rec = Recorder()
    service = NotificationService(session)
    service._senders = {DevicePlatform.EXPO_ANDROID: rec}
    return service, rec


async def give_device(sf, user_id):
    async with sf() as s:
        s.add(Device(user_id=user_id, platform=DevicePlatform.EXPO_ANDROID, expo_push_token=f"ExponentPushToken[{user_id}]"))
        await s.commit()


async def opt_in(client, headers, kind):
    r = await client.put(f"{API}/notifications/content-preferences", json={"kind": kind, "enabled": True}, headers=headers)
    assert r.status_code == 200


@pytest.fixture
async def world(session_factory):
    comp = await make_competition(session_factory)
    red, blue, green = [await make_team(session_factory, n) for n in ("Reds", "Blues", "Greens")]
    for i, (h, a, hs, as_) in enumerate([(red, green, 2, 0), (green, red, 0, 1), (red, green, 3, 3), (green, red, 1, 2), (red, green, 1, 0)]):
        await make_match(session_factory, comp, h, a, 40 - i * 6, hs, as_)
    for i in range(4):
        await make_match(session_factory, comp, blue, green, 38 - i * 6, 0, 1)
    upcoming = await make_match(session_factory, comp, red, blue, -0.5, status=MatchStatus.SCHEDULED)
    return dict(comp=comp, red=red, blue=blue, green=green, upcoming=upcoming)


# -- reactions: the three new kinds -------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["heart", "laugh", "clap", "fire"])
async def test_new_reaction_kinds_work_and_replace_each_other(client, make_user, world, kind):
    _, fan = await make_user("fan@example.com")
    first = await client.put(f"{API}/reactions/match/{world['upcoming']}", json={"kind": "goal"}, headers=fan)
    assert first.status_code == 200
    r = await client.put(f"{API}/reactions/match/{world['upcoming']}", json={"kind": kind}, headers=fan)
    body = r.json()
    assert body["mine"] == kind and body["total"] == 1 and body["counts"][kind] == 1 and body["counts"]["goal"] == 0
    assert set(body["counts"]) == {"thumbs_up", "fire", "wow", "goal", "heart", "laugh", "clap"}
    bad = await client.put(f"{API}/reactions/match/{world['upcoming']}", json={"kind": "poop"}, headers=fan)
    assert bad.status_code == 422


# -- profile reports and suspension --------------------------------------------------------------------


async def test_only_public_profiles_can_be_reported_once_each_and_not_your_own(client, make_user):
    target, th = await make_user("target@example.com")
    reporter, rh = await make_user("rep@example.com")
    assert (await client.post(f"{API}/profiles/{target.id}/report", json={"reason": "rude bio"}, headers=rh)).status_code == 404  # private: indistinguishable from missing
    await client.patch(f"{API}/users/me/profile", json={"profile_public": True}, headers=th)
    assert (await client.post(f"{API}/profiles/{target.id}/report", json={"reason": "x"})).status_code == 401
    assert (await client.post(f"{API}/profiles/{target.id}/report", json={"reason": "rude bio"}, headers=th)).status_code == 400
    assert (await client.post(f"{API}/profiles/{target.id}/report", json={"reason": "rude bio"}, headers=rh)).status_code == 204
    assert (await client.post(f"{API}/profiles/{target.id}/report", json={"reason": "again"}, headers=rh)).status_code == 204  # harmless duplicate
    assert (await client.post(f"{API}/profiles/{target.id}/report", json={"reason": "y" * 500}, headers=rh)).status_code == 422


async def test_moderators_review_and_resolve_profile_reports(client, make_user, session_factory):
    target, th = await make_user("target@example.com")
    _, rh = await make_user("rep@example.com")
    _, fan = await make_user("fan@example.com")
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    await client.patch(f"{API}/users/me/profile", json={"profile_public": True}, headers=th)
    await client.post(f"{API}/profiles/{target.id}/report", json={"reason": "offensive"}, headers=rh)
    assert (await client.get(f"{API}/moderation/profile-reports", headers=fan)).status_code == 403
    listed = (await client.get(f"{API}/moderation/profile-reports", headers=editor)).json()
    assert listed["total"] == 1 and listed["items"][0]["reason"] == "offensive" and listed["items"][0]["profile_user_id"] == target.id
    rid = listed["items"][0]["id"]
    assert (await client.post(f"{API}/moderation/profile-reports/{rid}/explode", headers=editor)).status_code == 422
    assert (await client.post(f"{API}/moderation/profile-reports/{rid}/resolve", headers=editor)).status_code == 204
    assert (await client.get(f"{API}/moderation/profile-reports", headers=editor)).json()["total"] == 0
    assert (await client.get(f"{API}/moderation/profile-reports?status=resolved", headers=editor)).json()["total"] == 1


async def test_only_admins_suspend_and_suspension_locks_the_account_out_everywhere(client, make_user):
    victim, vh = await make_user("victim@example.com")
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    admin, ah = await make_user("admin@example.com", UserRole.ADMIN)
    assert (await client.get(f"{API}/subscription", headers=vh)).status_code == 200
    assert (await client.post(f"{API}/moderation/users/{victim.id}/suspend", json={"reason": "spam"}, headers=editor)).status_code == 403
    assert (await client.post(f"{API}/moderation/users/{admin.id}/suspend", json={}, headers=ah)).status_code == 400  # not yourself / other admins
    assert (await client.post(f"{API}/moderation/users/999999/suspend", json={}, headers=ah)).status_code == 404
    assert (await client.post(f"{API}/moderation/users/{victim.id}/suspend", json={"reason": "spam"}, headers=ah)).status_code == 204

    assert (await client.get(f"{API}/subscription", headers=vh)).status_code == 401  # existing token no longer works
    posting = await client.post(f"{API}/comments", json={"target_type": "match", "target_id": 1, "body": "hello"}, headers=vh)
    assert posting.status_code == 401
    login = await client.post(f"{API}/auth/login", json={"email": "victim@example.com", "password": "Sup3rSecret!"})
    assert login.status_code == 403 and "suspended" in login.json()["detail"]
    wrong = await client.post(f"{API}/auth/login", json={"email": "victim@example.com", "password": "wrong-password"})
    assert wrong.status_code == 401  # a stranger can't learn the account is suspended

    assert (await client.post(f"{API}/moderation/users/{victim.id}/unsuspend", headers=ah)).status_code == 204
    assert (await client.get(f"{API}/subscription", headers=vh)).status_code == 200


# -- community signals in the feed ------------------------------------------------------------------------


async def test_commenting_on_a_match_surfaces_it_in_the_feed_with_an_explanation(client, make_user, world, fake_redis):
    user, fan = await make_user("fan@example.com")
    before = (await client.get(f"{API}/feed", headers=fan)).json()
    assert not any(i["reason"] == "community_match" for i in before["items"]) and before["personalised"] is False
    posted = await client.post(f"{API}/comments", json={"target_type": "match", "target_id": world["upcoming"], "body": "Big game"}, headers=fan)
    assert posted.status_code == 201
    await fake_redis.delete(RedisKeys.user_feed(user.id))  # the per-user feed cache lives ~45s; skip the wait
    feed = (await client.get(f"{API}/feed", headers=fan)).json()
    hits = [i for i in feed["items"] if i["reason"] == "community_match"]
    assert feed["personalised"] is True and len(hits) == 1 and hits[0]["match"]["id"] == world["upcoming"]
    assert "conversation" in hits[0]["explanation"]
    other, oh = await make_user("other@example.com")
    assert not any(i["reason"] == "community_match" for i in (await client.get(f"{API}/feed", headers=oh)).json()["items"])  # not shared across users


async def test_community_feed_signal_rank_is_below_live_and_today(session_factory, world, make_user, fake_redis):
    from app.services.article_service import ArticleService
    from app.services.discovery_service import FEED_TIERS, DiscoveryService

    assert FEED_TIERS["live_followed_match"] < FEED_TIERS["community_match"] <= FEED_TIERS["followed_team_upcoming"] + 0
    assert FEED_TIERS["community_article"] < FEED_TIERS["trending"]
    user, _ = await make_user("fan@example.com")
    async with session_factory() as db:
        from app.models.community import Comment
        from app.models.enums import CommentTarget

        db.add(Comment(user_id=user.id, target_type=CommentTarget.MATCH, target_id=world["upcoming"], body="Big game"))
        await db.commit()
        svc = DiscoveryService(db, fake_redis, ArticleService(db, fake_redis))
        db_user = await db.get(User, user.id)
        feed = await svc._build_feed(db_user)
    hits = [i for i in feed.items if i.reason == "community_match"]
    assert len(hits) == 1 and hits[0].match.id == world["upcoming"]
    assert "conversation" in hits[0].explanation and hits[0].rank == FEED_TIERS["community_match"]
    assert feed.personalised is True


async def test_old_interactions_do_not_influence_the_feed(session_factory, world, make_user, fake_redis):
    from app.models.community import Comment
    from app.models.enums import CommentTarget
    from app.services.article_service import ArticleService
    from app.services.discovery_service import DiscoveryService

    user, _ = await make_user("fan@example.com")
    async with session_factory() as db:
        db.add(Comment(user_id=user.id, target_type=CommentTarget.MATCH, target_id=world["upcoming"], body="ages ago", created_at=NOW - timedelta(days=40)))
        await db.commit()
        feed = await DiscoveryService(db, fake_redis, ArticleService(db, fake_redis))._build_feed(await db.get(User, user.id))
    assert not any(i.reason == "community_match" for i in feed.items)
    assert feed.personalised is False  # follows nothing and has no recent activity: the general feed, labelled as such


# -- persisted insights ---------------------------------------------------------------------------------------


async def test_insight_generation_stores_sourced_records_and_is_idempotent(session_factory, world):
    async with session_factory() as db:
        gen = InsightGenerator(db)
        wrote = await gen.generate_for_match(world["upcoming"])
        assert wrote > 0
        rows = await gen.read(InsightEntityType.MATCH, world["upcoming"])
        assert rows and all(r.source_data_version and r.generated_at for r in rows)
        assert any(r.insight_type.startswith("home:") for r in rows)
        stamp = {r.insight_type: (r.generated_at, r.source_data_version) for r in rows}
        assert await gen.generate_for_match(world["upcoming"]) == 0  # unchanged data -> nothing rewritten
        again = {r.insight_type: (r.generated_at, r.source_data_version) for r in await gen.read(InsightEntityType.MATCH, world["upcoming"])}
        assert again == stamp
        # new finished result for Reds -> the data version changes and the set is regenerated as a whole
        await make_match(session_factory, world["comp"], world["red"], world["green"], 1, 4, 0)
        assert await gen.generate_for_match(world["upcoming"]) > 0
        assert {r.source_data_version for r in await gen.read(InsightEntityType.MATCH, world["upcoming"])} != {v for _, v in stamp.values()}


async def test_insight_text_is_backed_by_the_data(session_factory, world):
    async with session_factory() as db:
        gen = InsightGenerator(db)
        await gen.generate_for_team(world["red"])
        texts = [r.text for r in await gen.read(InsightEntityType.TEAM, world["red"])]
    assert any(t.startswith("Reds: won 4, drew 1, lost 0 of the last 5") for t in texts), texts


async def test_live_insights_need_both_teams_statistics_and_real_margins():
    class S:
        def __init__(self, **kw):
            self.shots = self.shots_on_target = self.possession = None
            self.__dict__.update(kw)

    assert live_insights("A", "B", S(shots=9), None) == []
    assert live_insights("A", "B", S(shots=None), S(shots=3)) == []
    out = live_insights("A", "B", S(shots=11, possession=64.0, shots_on_target=5), S(shots=3, possession=36.0, shots_on_target=1))
    assert {i.key for i in out} == {"live_shots", "live_possession", "live_on_target"}
    assert "11 shots to B's 3" in out[0].text
    assert live_insights("A", "B", S(shots=2, possession=52.0), S(shots=1, possession=48.0)) == []  # nothing remarkable: say nothing


async def test_live_match_insights_are_generated_from_stored_statistics(session_factory, world):
    live = await make_match(
        session_factory, world["comp"], world["red"], world["blue"], 0, 1, 0, status=MatchStatus.LIVE,
        stats={world["red"]: dict(shots=12, shots_on_target=6, possession=65.0), world["blue"]: dict(shots=2, shots_on_target=0, possession=35.0)},
    )
    async with session_factory() as db:
        gen = InsightGenerator(db)
        await gen.generate_for_match(live)
        types = {r.insight_type for r in await gen.read(InsightEntityType.MATCH, live)}
    assert {"live:live_shots", "live:live_possession"} <= types


async def test_player_insights_only_state_what_the_numbers_support(session_factory, world, client):
    scorer = await make_player(session_factory, "Sam Scorer", world["red"])
    mate = await make_player(session_factory, "Mia Maker", world["red"])
    async with session_factory() as db:
        match_ids = (await db.execute(select(Match.id).where(Match.status == MatchStatus.FINISHED, Match.home_team_id == world["red"]).order_by(Match.kickoff_time))).scalars().all()
    for i, mid in enumerate(match_ids[:3]):
        await add_player_stats(session_factory, mid, scorer, world["red"], minutes_played=90, goals=1 if i < 2 else 0, assists=0, key_passes=1)
        await add_player_stats(session_factory, mid, mate, world["red"], minutes_played=90, goals=0, assists=0, key_passes=4)
    async with session_factory() as db:
        gen = InsightGenerator(db)
        await gen.generate_for_player(scorer)
        await gen.generate_for_player(mate)
        scorer_texts = [r.text for r in await gen.read(InsightEntityType.PLAYER, scorer)]
        mate_texts = [r.text for r in await gen.read(InsightEntityType.PLAYER, mate)]
    assert any("scored in 2 of the last 3" in t for t in scorer_texts)
    assert not any("most chances" in t for t in scorer_texts)
    assert any("created the most chances for Reds" in t and "(12)" in t for t in mate_texts)
    api = (await client.get(f"{API}/players/{mate}/insights")).json()
    assert api and api[0]["entity_type"] == "player" and api[0]["source_data_version"]
    nothing = await make_player(session_factory, "Bench Warmer", world["red"])
    assert (await client.get(f"{API}/players/{nothing}/insights")).json() == []
    assert (await client.get(f"{API}/players/999999/insights")).status_code == 404


async def test_stored_insights_are_served_for_matches_and_teams(client, session_factory, world):
    async with session_factory() as db:
        await InsightGenerator(db).generate_for_match(world["upcoming"])
        await InsightGenerator(db).generate_for_team(world["red"])
    assert (await client.get(f"{API}/matches/{world['upcoming']}/insight-records")).json()
    assert (await client.get(f"{API}/teams/{world['red']}/insight-records")).json()
    assert (await client.get(f"{API}/matches/999999/insight-records")).status_code == 404


# -- personal insights and the Phase 6b notifications -------------------------------------------------------------


async def test_personal_insights_reflect_only_your_favourites(client, session_factory, world, make_user):
    fan, fh = await make_user("fan@example.com")
    stranger, sh = await make_user("stranger@example.com")
    assert (await client.get(f"{API}/me/insights")).status_code == 401
    assert (await client.get(f"{API}/me/insights", headers=fh)).json() == []
    async with session_factory() as db:
        db.add(FavouriteTeam(user_id=fan.id, team_id=world["red"]))
        await db.commit()
        kickoff = (await db.get(Match, world["upcoming"])).kickoff_time
        game_day = await personal_insights.for_user(db, fan.id, now=kickoff - timedelta(hours=1))
        week_later = await personal_insights.for_user(db, fan.id, now=kickoff + timedelta(days=2))
        nobody = await personal_insights.for_user(db, stranger.id, now=kickoff - timedelta(hours=1))
    today = [i for i in game_day if i.key == "team_today"]
    assert len(today) == 1 and f"Reds play Blues today at {kickoff:%H:%M} UTC." == today[0].text and today[0].entity_id == world["upcoming"]
    assert nobody == []  # only your own favourites
    # two days after, the fixture is in the past (still SCHEDULED in the data), so nothing is claimed about it
    assert not any(i.key == "team_today" for i in week_later)


async def test_prediction_matchday_and_poll_notifications_respect_preferences_and_dedupe(client, session_factory, world, make_user):
    fan, fh = await make_user("fan@example.com")
    quiet, qh = await make_user("quiet@example.com")
    for u in (fan, quiet):
        await give_device(session_factory, u.id)
        async with session_factory() as db:
            db.add(FavouriteTeam(user_id=u.id, team_id=world["red"]))
            await db.commit()
    for kind in ("prediction_available", "team_insights", "poll_closing"):
        await opt_in(client, fh, kind)  # only `fan` opts in; `quiet` keeps the defaults (off)

    async with session_factory() as db:
        service, rec = await notifier(db)
        assert await personal_insights.notify_prediction_available(db, world["upcoming"], service=service) == 1
        assert [uid for uid, _ in rec.sent] == [fan.id] and "estimate" in rec.sent[0][1].title.lower()
        assert await personal_insights.notify_prediction_available(db, world["upcoming"], service=service) == 0  # once only
        assert await personal_insights.notify_matchday(db, service=service) == 1
        assert await personal_insights.notify_matchday(db, service=service) == 0
        # a poll for the match closing soon, which `fan` has not voted in
        poll = Poll(question="Who wins?", kind=PollKind.MATCH, status=PollStatus.OPEN, match_id=world["upcoming"], closes_at=datetime.now(timezone.utc) + timedelta(minutes=30))
        db.add(poll)
        await db.flush()
        db.add_all([PollOption(poll_id=poll.id, label="Reds", position=0), PollOption(poll_id=poll.id, label="Blues", position=1)])
        await db.commit()
        assert await personal_insights.notify_polls_closing(db, service=service) == 1
        assert await personal_insights.notify_polls_closing(db, service=service) == 0
        titles = {p.title for _, p in rec.sent}
    assert titles == {"Match estimate available", "Match coming up", "Poll closing soon"}
    assert all(uid == fan.id for uid, _ in rec.sent)


async def test_nobody_is_notified_about_matches_that_already_started_or_have_no_followers(client, session_factory, world, make_user):
    fan, fh = await make_user("fan@example.com")
    await give_device(session_factory, fan.id)
    await opt_in(client, fh, "prediction_available")
    async with session_factory() as db:
        service, rec = await notifier(db)
        assert await personal_insights.notify_prediction_available(db, world["upcoming"], service=service) == 0  # nobody follows it
        db.add(FavouriteTeam(user_id=fan.id, team_id=world["red"]))
        await db.execute(update(Match).where(Match.id == world["upcoming"]).values(status=MatchStatus.LIVE))
        await db.commit()
        assert await personal_insights.notify_prediction_available(db, world["upcoming"], service=service) == 0
    assert rec.sent == []


async def test_subscription_notifications_are_on_by_default_and_can_be_switched_off(client, session_factory, make_user):
    user, headers = await make_user("fan@example.com")
    await give_device(session_factory, user.id)
    async with session_factory() as db:
        service, rec = await notifier(db)
        assert await personal_insights.notify_subscription_event(db, user.id, "subscription.activated", "evt_1", service=service) == 1
        assert await personal_insights.notify_subscription_event(db, user.id, "subscription.activated", "evt_1", service=service) == 0
        assert await personal_insights.notify_subscription_event(db, user.id, "payment.failed", "evt_2", service=service) == 1
        assert await personal_insights.notify_subscription_event(db, user.id, "unknown.kind", "evt_3", service=service) == 0
        await client.put(f"{API}/notifications/content-preferences", json={"kind": "subscription_events", "enabled": False}, headers=headers)
        assert await personal_insights.notify_subscription_event(db, user.id, "subscription.expired", "evt_4", service=service) == 0
    assert [p.title for _, p in rec.sent] == ["Premium is active", "Payment problem"]


# -- real-time routing -------------------------------------------------------------------------------------------------


class FakeManager:
    def __init__(self):
        self.general, self.match = [], []

    async def broadcast_general(self, payload):
        self.general.append(payload)

    async def broadcast_to_match(self, match_id, payload):
        self.match.append((match_id, payload))


async def test_community_events_reach_the_match_page_but_not_the_livescore_board(fake_redis):
    manager = FakeManager()
    bridge = PubSubBridge(fake_redis, manager)
    await bridge._dispatch({"type": "comment.created", "match_id": "7", "data": {"comment_id": 3}})
    await bridge._dispatch({"type": "GOAL", "match_id": "7", "data": {}})
    assert [t for _, t in [(m, p["type"]) for m, p in manager.match]] == ["comment.created", "GOAL"]
    assert [p["type"] for p in manager.general] == ["GOAL"]  # live match events still go to the board


async def test_a_match_comment_and_a_vote_publish_throttled_ids_only_events(client, make_user, world, fake_redis, session_factory):
    pubsub = fake_redis.raw.pubsub()
    await pubsub.subscribe(RedisKeys.MATCH_EVENTS_CHANNEL)
    await pubsub.get_message(timeout=0.1)
    _, fan = await make_user("fan@example.com")
    for body in ("first", "second one is different"):
        assert (await client.post(f"{API}/comments", json={"target_type": "match", "target_id": world["upcoming"], "body": body}, headers=fan)).status_code == 201
    first = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
    assert first and '"comment.created"' in first["data"] and "first" not in first["data"]  # an id, not the text
    assert await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2) is None  # the burst was throttled
    await client.put(f"{API}/reactions/match/{world['upcoming']}", json={"kind": "heart"}, headers=fan)
    reaction = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
    assert reaction and '"comment.reaction"' in reaction["data"]
    article = await client.post(f"{API}/comments", json={"target_type": "article", "target_id": 1, "body": "no match here"}, headers=fan)
    assert article.status_code in (201, 404)
    assert RealtimeEventType.COMMENT_CREATED.value == "comment.created"
