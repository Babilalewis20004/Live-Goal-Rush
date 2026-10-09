"""Comment-reply, poll-result and editorial notifications (Phase 6): preferences
are respected, nothing is sent twice, nobody is told about their own actions."""

import pytest
from sqlalchemy import select

from app.models.community import Poll, SocialNotificationLog
from app.models.device import Device
from app.models.enums import ContentNotificationKind, DevicePlatform, PollStatus, UserRole
from app.services import social_notification_service as social
from app.services.content_notification_service import CONTENT_DEFAULTS
from app.services.notifications.base import DeliveryResult, PushSender
from app.services.notifications.service import NotificationService

API = "/api/v1"


class Recorder(PushSender):
    def __init__(self):
        self.sent = []

    async def send(self, device, payload):
        self.sent.append((device.user_id, payload))
        return DeliveryResult(success=True)


async def _service(session):
    recorder = Recorder()
    service = NotificationService(session)
    service._senders = {DevicePlatform.EXPO_ANDROID: recorder}
    return service, recorder


async def _device(session_factory, user_id):
    async with session_factory() as session:
        session.add(Device(user_id=user_id, platform=DevicePlatform.EXPO_ANDROID, expo_push_token=f"ExponentPushToken[{user_id}]"))
        await session.commit()


@pytest.fixture
async def article(client, make_user, publish_article):
    _, editor = await make_user("owner@example.com", UserRole.EDITOR)
    return await publish_article(editor, "Discussion piece")


def test_defaults_match_the_documented_policy():
    assert CONTENT_DEFAULTS[ContentNotificationKind.COMMENT_REPLIES] is True
    assert CONTENT_DEFAULTS[ContentNotificationKind.EDITORIAL_UPDATES] is True
    assert CONTENT_DEFAULTS[ContentNotificationKind.POLL_RESULTS] is False
    for kind in ("team_news", "competition_news", "match_reports", "transfer_news", "general_news"):
        assert CONTENT_DEFAULTS[ContentNotificationKind(kind)] is False  # the news kinds stay opt-in


async def test_new_kinds_are_listed_in_the_preferences_api(client, make_user):
    _, fan = await make_user("fan@example.com")
    prefs = {p["kind"]: p for p in (await client.get(f"{API}/notifications/content-preferences", headers=fan)).json()}
    assert prefs["comment_replies"]["enabled"] is True and prefs["comment_replies"]["default"] is True
    assert prefs["poll_results"]["enabled"] is False
    assert prefs["editorial_updates"]["enabled"] is True
    r = await client.put(f"{API}/notifications/content-preferences", json={"kind": "comment_replies", "enabled": False}, headers=fan)
    assert r.json() == {"kind": "comment_replies", "enabled": False, "default": True}


# -- comment replies ------------------------------------------------------------------------------------


async def test_a_reply_notifies_the_parent_author_with_a_deep_link(client, make_user, article, session_factory):
    alice, alice_h = await make_user("alice@example.com")
    _, bob_h = await make_user("bob@example.com")
    await _device(session_factory, alice.id)
    top = (await client.post(f"{API}/comments", json={"target_type": "article", "target_id": article["id"], "body": "Original"}, headers=alice_h)).json()
    reply = (await client.post(f"{API}/comments", json={"target_type": "article", "target_id": article["id"], "body": "I replied", "parent_id": top["id"]}, headers=bob_h)).json()
    async with session_factory() as session:
        service, recorder = await _service(session)
        assert await social.notify_comment_reply(session, reply["id"], service=service) == 1
        assert await social.notify_comment_reply(session, reply["id"], service=service) == 0  # a retried task sends nothing
    user_id, payload = recorder.sent[0]
    assert user_id == alice.id and payload.data == {"type": "article", "id": article["slug"]}
    assert "Bob" in payload.title and payload.body == "I replied"


async def test_replying_to_yourself_or_a_match_comment(client, make_user, article, session_factory):
    from app.models.match import Match

    alice, alice_h = await make_user("alice@example.com")
    bob, bob_h = await make_user("bob@example.com")
    await _device(session_factory, alice.id)
    top = (await client.post(f"{API}/comments", json={"target_type": "article", "target_id": article["id"], "body": "Mine"}, headers=alice_h)).json()
    own = (await client.post(f"{API}/comments", json={"target_type": "article", "target_id": article["id"], "body": "Talking to myself", "parent_id": top["id"]}, headers=alice_h)).json()
    async with session_factory() as session:
        service, recorder = await _service(session)
        assert await social.notify_comment_reply(session, own["id"], service=service) == 0
        assert await social.notify_comment_reply(session, top["id"], service=service) == 0  # not a reply
        assert recorder.sent == []


async def test_reply_notifications_respect_the_preference(client, make_user, article, session_factory):
    alice, alice_h = await make_user("alice@example.com")
    _, bob_h = await make_user("bob@example.com")
    await _device(session_factory, alice.id)
    await client.put(f"{API}/notifications/content-preferences", json={"kind": "comment_replies", "enabled": False}, headers=alice_h)
    top = (await client.post(f"{API}/comments", json={"target_type": "article", "target_id": article["id"], "body": "Original"}, headers=alice_h)).json()
    reply = (await client.post(f"{API}/comments", json={"target_type": "article", "target_id": article["id"], "body": "Reply", "parent_id": top["id"]}, headers=bob_h)).json()
    async with session_factory() as session:
        service, recorder = await _service(session)
        assert await social.notify_comment_reply(session, reply["id"], service=service) == 0
    assert recorder.sent == []


async def test_a_reply_that_was_hidden_or_whose_parent_was_deleted_sends_nothing(client, make_user, article, session_factory):
    alice, alice_h = await make_user("alice@example.com")
    _, bob_h = await make_user("bob@example.com")
    await _device(session_factory, alice.id)
    top = (await client.post(f"{API}/comments", json={"target_type": "article", "target_id": article["id"], "body": "Original"}, headers=alice_h)).json()
    reply = (await client.post(f"{API}/comments", json={"target_type": "article", "target_id": article["id"], "body": "Reply", "parent_id": top["id"]}, headers=bob_h)).json()
    await client.delete(f"{API}/comments/{top['id']}", headers=alice_h)
    async with session_factory() as session:
        service, recorder = await _service(session)
        assert await social.notify_comment_reply(session, reply["id"], service=service) == 0


# -- editorial -------------------------------------------------------------------------------------------


async def test_editorial_notifications_go_to_the_right_people(client, make_user, session_factory):
    author, author_h = await make_user("author@example.com", UserRole.AUTHOR)
    editor, editor_h = await make_user("editor@example.com", UserRole.EDITOR)
    admin, _ = await make_user("admin@example.com", UserRole.ADMIN)
    fan, _ = await make_user("fan@example.com")
    for u in (author, editor, admin, fan):
        await _device(session_factory, u.id)
    article = (await client.post(f"{API}/editor/articles", json={"title": "For review", "content": "<p>Text</p>"}, headers=author_h)).json()

    await client.post(f"{API}/editor/articles/{article['id']}/submit", headers=author_h)
    async with session_factory() as session:
        service, recorder = await _service(session)
        assert await social.notify_editorial(session, article["id"], "submitted", service=service) == 2
        assert {uid for uid, _ in recorder.sent} == {editor.id, admin.id}  # reviewers, not the author, not fans
        assert recorder.sent[0][1].data == {"type": "editor", "id": article["id"]}
        assert await social.notify_editorial(session, article["id"], "submitted", service=service) == 0  # once

    await client.post(f"{API}/editor/articles/{article['id']}/approve", headers=editor_h)
    async with session_factory() as session:
        service, recorder = await _service(session)
        assert await social.notify_editorial(session, article["id"], "published", service=service) == 1
        user_id, payload = recorder.sent[0]
        assert user_id == author.id and payload.data == {"type": "article", "id": article["slug"]}
        assert await social.notify_editorial(session, article["id"], "rejected", service=service) == 0  # state doesn't match the event


async def test_rejection_tells_the_author_why(client, make_user, session_factory):
    author, author_h = await make_user("author@example.com", UserRole.AUTHOR)
    _, editor_h = await make_user("editor@example.com", UserRole.EDITOR)
    await _device(session_factory, author.id)
    article = (await client.post(f"{API}/editor/articles", json={"title": "Needs work", "content": "<p>Text</p>"}, headers=author_h)).json()
    await client.post(f"{API}/editor/articles/{article['id']}/submit", headers=author_h)
    await client.post(f"{API}/editor/articles/{article['id']}/reject", json={"note": "Check the score line"}, headers=editor_h)
    async with session_factory() as session:
        service, recorder = await _service(session)
        assert await social.notify_editorial(session, article["id"], "rejected", service=service) == 1
    assert recorder.sent[0][1].body == "Check the score line" and recorder.sent[0][1].title == "Changes requested"


async def test_editorial_updates_can_be_switched_off(client, make_user, session_factory):
    author, author_h = await make_user("author@example.com", UserRole.AUTHOR)
    _, editor_h = await make_user("editor@example.com", UserRole.EDITOR)
    await _device(session_factory, author.id)
    await client.put(f"{API}/notifications/content-preferences", json={"kind": "editorial_updates", "enabled": False}, headers=author_h)
    article = (await client.post(f"{API}/editor/articles", json={"title": "Quiet one", "content": "<p>Text</p>"}, headers=author_h)).json()
    await client.post(f"{API}/editor/articles/{article['id']}/submit", headers=author_h)
    await client.post(f"{API}/editor/articles/{article['id']}/approve", headers=editor_h)
    async with session_factory() as session:
        service, recorder = await _service(session)
        assert await social.notify_editorial(session, article["id"], "published", service=service) == 0


# -- poll results ------------------------------------------------------------------------------------------


async def _closed_poll(client, make_user, session_factory, *, votes):
    editor, editor_h = await make_user("editor@example.com", UserRole.EDITOR)
    poll = (await client.post(f"{API}/editor/polls", json={"question": "Who wins the derby?", "kind": "question", "options": ["Red", "Blue"]}, headers=editor_h)).json()
    voters = []
    for i, choice in enumerate(votes):
        user, headers = await make_user(f"voter{i}@example.com")
        await _device(session_factory, user.id)
        await client.post(f"{API}/polls/{poll['id']}/vote", json={"option_id": poll["options"][choice]["id"]}, headers=headers)
        voters.append((user, headers))
    await client.post(f"{API}/editor/polls/{poll['id']}/close", headers=editor_h)
    return poll, voters


async def test_poll_results_go_only_to_voters_who_opted_in_and_only_once(client, make_user, session_factory):
    poll, voters = await _closed_poll(client, make_user, session_factory, votes=[0, 0, 1])
    (opted, opted_h), (off, _), (also_opted, also_h) = voters
    for headers in (opted_h, also_h):
        await client.put(f"{API}/notifications/content-preferences", json={"kind": "poll_results", "enabled": True}, headers=headers)
    async with session_factory() as session:
        service, recorder = await _service(session)
        assert await social.notify_poll_results(session, poll["id"], service=service) == 2
        assert {uid for uid, _ in recorder.sent} == {opted.id, also_opted.id}  # `off` never opted in
        assert await social.notify_poll_results(session, poll["id"], service=service) == 0  # announced once
    payload = recorder.sent[0][1]
    assert "Red" in payload.body and "67%" in payload.body and payload.data == {"type": "poll", "id": poll["id"]}


async def test_an_open_poll_is_never_announced(client, make_user, session_factory):
    editor, editor_h = await make_user("editor@example.com", UserRole.EDITOR)
    poll = (await client.post(f"{API}/editor/polls", json={"question": "Still open here", "options": ["A", "B"]}, headers=editor_h)).json()
    async with session_factory() as session:
        service, recorder = await _service(session)
        assert await social.notify_poll_results(session, poll["id"], service=service) == 0
        assert (await session.get(Poll, poll["id"])).status == PollStatus.OPEN
    assert recorder.sent == []


async def test_dedup_ledger_blocks_a_second_delivery_for_the_same_key(session_factory, make_user):
    user, _ = await make_user("fan@example.com")
    await _device(session_factory, user.id)
    async with session_factory() as session:
        service, recorder = await _service(session)
        args = (session, {user.id}, ContentNotificationKind.COMMENT_REPLIES, "reply:42", "T", "B", {"type": "match", "id": 1})
        assert await social.deliver(*args, service=service) == 1
        assert await social.deliver(*args, service=service) == 0
        assert len((await session.execute(select(SocialNotificationLog))).scalars().all()) == 1
