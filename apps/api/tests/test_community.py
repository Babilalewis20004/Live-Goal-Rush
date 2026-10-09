"""Comments, moderation, reactions and polls (Phase 6)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.models.community import PollVote
from app.models.enums import UserRole
from app.models.match import Match
from app.models.user import User

API = "/api/v1"


@pytest.fixture
async def article(client, make_user, publish_article):
    _, editor = await make_user("editor-owner@example.com", UserRole.EDITOR)
    return await publish_article(editor, "Talking point")


async def _comment(client, headers, target_id, body="Great read", target_type="article", parent_id=None):
    payload = {"target_type": target_type, "target_id": target_id, "body": body}
    if parent_id:
        payload["parent_id"] = parent_id
    return await client.post(f"{API}/comments", json=payload, headers=headers)


async def _match_id(session_factory):
    async with session_factory() as session:
        return (await session.execute(select(Match.id).limit(1))).scalar_one()


async def _age_account(session_factory, user_id):
    async with session_factory() as session:
        await session.execute(update(User).where(User.id == user_id).values(created_at=datetime.now(timezone.utc) - timedelta(days=2)))
        await session.commit()


# -- comments: writing -------------------------------------------------------------------------------


async def test_commenting_needs_an_account_but_reading_does_not(client, make_user, article):
    assert (await _comment(client, {}, article["id"])).status_code == 401
    _, fan = await make_user("fan@example.com")
    created = await _comment(client, fan, article["id"], "First!")
    assert created.status_code == 201
    body = created.json()
    assert body["body"] == "First!" and body["mine"] is True and body["author"]["display_name"] == "Fan"
    assert "fan@example.com" not in created.text  # a display name, never an email
    listing = (await client.get(f"{API}/comments", params={"target_type": "article", "target_id": article["id"]})).json()
    assert listing["total"] == 1 and listing["total_comments"] == 1 and listing["items"][0]["body"] == "First!"
    assert listing["items"][0]["mine"] is False  # anonymous viewer


async def test_comments_work_on_matches_and_unknown_or_unpublished_targets_404(seeded_client, make_user, session_factory, publish_article):
    _, fan = await make_user("fan@example.com")
    match_id = await _match_id(session_factory)
    assert (await _comment(seeded_client, fan, match_id, "What a game", "match")).status_code == 201
    assert (await _comment(seeded_client, fan, 999999, "Ghost", "match")).status_code == 404
    assert (await _comment(seeded_client, fan, 999999, "Ghost")).status_code == 404
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    draft = await publish_article(editor, "Unpublished", publish=False)
    assert (await _comment(seeded_client, fan, draft["id"])).status_code == 404
    listed = await seeded_client.get(f"{API}/comments", params={"target_type": "article", "target_id": draft["id"]})
    assert listed.status_code == 404


async def test_replies_are_one_level_deep(client, make_user, article):
    _, alice = await make_user("alice@example.com")
    _, bob = await make_user("bob@example.com")
    top = (await _comment(client, alice, article["id"], "Top level")).json()
    reply = (await _comment(client, bob, article["id"], "A reply", parent_id=top["id"])).json()
    nested = (await _comment(client, alice, article["id"], "Reply to the reply", parent_id=reply["id"])).json()
    assert reply["parent_id"] == top["id"] and nested["parent_id"] == top["id"]  # flattened onto the top-level comment
    page = (await client.get(f"{API}/comments", params={"target_type": "article", "target_id": article["id"]})).json()
    assert page["total"] == 1 and page["total_comments"] == 3
    assert [r["body"] for r in page["items"][0]["replies"]] == ["A reply", "Reply to the reply"]
    assert page["items"][0]["reply_count"] == 2


async def test_replies_must_stay_on_the_same_target(client, make_user, article, publish_article):
    _, alice = await make_user("alice@example.com")
    _, editor = await make_user("editor2@example.com", UserRole.EDITOR)
    other = await publish_article(editor, "A different story")
    top = (await _comment(client, alice, article["id"], "Over here")).json()
    assert (await _comment(client, alice, other["id"], "Wrong place", parent_id=top["id"])).status_code == 422
    assert (await _comment(client, alice, article["id"], "Orphan", parent_id=424242)).status_code == 422


@pytest.mark.parametrize("body", ["", "   \n  ", "\x00\x01"])
async def test_blank_comments_are_rejected(client, make_user, article, body):
    _, fan = await make_user("fan@example.com")
    assert (await _comment(client, fan, article["id"], body)).status_code == 422


async def test_length_link_and_duplicate_rules(client, make_user, article, session_factory):
    user, fan = await make_user("fan@example.com")
    assert (await _comment(client, fan, article["id"], "x" * (settings.comment_max_length + 1))).status_code == 422
    assert (await _comment(client, fan, article["id"], "x" * settings.comment_max_length)).status_code == 201
    # a brand-new account cannot post links at all
    assert (await _comment(client, fan, article["id"], "see https://example.com")).status_code == 422
    await _age_account(session_factory, user.id)
    assert (await _comment(client, fan, article["id"], "see https://example.com")).status_code == 201
    too_many = "https://a.example https://b.example https://c.example"
    assert (await _comment(client, fan, article["id"], too_many)).status_code == 422
    assert (await _comment(client, fan, article["id"], "SEE https://example.com")).status_code == 422  # duplicate (case-insensitive)


async def test_comments_are_rate_limited_per_user(client, make_user, article):
    _, spammer = await make_user("spammer@example.com")
    _, other = await make_user("other@example.com")
    codes = [(await _comment(client, spammer, article["id"], f"comment number {i}")).status_code for i in range(settings.comments_per_minute + 1)]
    assert codes[:-1] == [201] * settings.comments_per_minute and codes[-1] == 429
    assert (await _comment(client, other, article["id"], "I am a different user")).status_code == 201


async def test_markup_is_stored_and_returned_as_inert_text(client, make_user, article):
    _, fan = await make_user("fan@example.com")
    evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    body = (await _comment(client, fan, article["id"], evil)).json()["body"]
    assert body == evil  # never interpreted server-side; every client renders comment bodies as text


async def test_editing_and_deleting_your_own_comment(client, make_user, article):
    _, alice = await make_user("alice@example.com")
    _, bob = await make_user("bob@example.com")
    top = (await _comment(client, alice, article["id"], "Original")).json()
    assert (await client.patch(f"{API}/comments/{top['id']}", json={"body": "Hijacked"}, headers=bob)).status_code == 403
    edited = (await client.patch(f"{API}/comments/{top['id']}", json={"body": "Edited"}, headers=alice)).json()
    assert edited["body"] == "Edited" and edited["edited_at"]
    page = (await client.get(f"{API}/comments", params={"target_type": "article", "target_id": article["id"]})).json()
    assert page["items"][0]["body"] == "Edited" and page["items"][0]["edited_at"]  # cache was invalidated
    assert (await client.delete(f"{API}/comments/{top['id']}", headers=bob)).status_code == 403
    assert (await client.delete(f"{API}/comments/{top['id']}", headers=alice)).status_code == 204
    assert (await client.patch(f"{API}/comments/{top['id']}", json={"body": "Zombie"}, headers=alice)).status_code == 404
    assert (await client.get(f"{API}/comments", params={"target_type": "article", "target_id": article["id"]})).json()["total"] == 0


async def test_a_deleted_comment_with_replies_leaves_a_placeholder(client, make_user, article):
    _, alice = await make_user("alice@example.com")
    _, bob = await make_user("bob@example.com")
    top = (await _comment(client, alice, article["id"], "Private thought")).json()
    await _comment(client, bob, article["id"], "I disagree", parent_id=top["id"])
    await client.delete(f"{API}/comments/{top['id']}", headers=alice)
    page = (await client.get(f"{API}/comments", params={"target_type": "article", "target_id": article["id"]})).json()
    placeholder = page["items"][0]
    assert placeholder["removed"] is True and placeholder["body"] == "" and placeholder["author"] is None
    assert "Private thought" not in str(page)
    assert [r["body"] for r in placeholder["replies"]] == ["I disagree"]


# -- comments: reading, caching, likes ---------------------------------------------------------------


async def test_pagination_and_sorting(client, make_user, article, monkeypatch):
    monkeypatch.setattr(settings, "comments_per_minute", 100)
    monkeypatch.setattr(settings, "comments_per_hour", 100)
    _, fan = await make_user("fan@example.com")
    _, other = await make_user("other@example.com")
    ids = [(await _comment(client, fan, article["id"], f"Comment {i}")).json()["id"] for i in range(5)]
    await client.put(f"{API}/comments/{ids[0]}/like", headers=other)
    q = {"target_type": "article", "target_id": article["id"], "page_size": 2}
    newest = (await client.get(f"{API}/comments", params={**q, "page": 1})).json()
    assert [c["body"] for c in newest["items"]] == ["Comment 4", "Comment 3"] and newest["total"] == 5
    assert [c["body"] for c in (await client.get(f"{API}/comments", params={**q, "page": 3})).json()["items"]] == ["Comment 0"]
    top = (await client.get(f"{API}/comments", params={**q, "sort": "top"})).json()
    assert top["items"][0]["body"] == "Comment 0"  # the liked one first
    assert (await client.get(f"{API}/comments", params={**q, "sort": "weird"})).status_code == 422
    assert (await client.get(f"{API}/comments", params={**q, "page_size": 51})).status_code == 422


async def test_pages_are_cached_in_redis_but_viewer_data_never_is(client, make_user, article, fake_redis):
    _, alice = await make_user("alice@example.com")
    _, bob = await make_user("bob@example.com")
    comment = (await _comment(client, alice, article["id"], "Likeable")).json()
    q = {"target_type": "article", "target_id": article["id"]}
    await client.put(f"{API}/comments/{comment['id']}/like", headers=bob)
    as_bob = (await client.get(f"{API}/comments", params=q, headers=bob)).json()["items"][0]
    assert as_bob["liked_by_me"] is True and as_bob["mine"] is False
    keys = [k async for k in fake_redis.raw.scan_iter(match="football:comments:article:*")]
    assert any(":newest:" in k for k in keys)
    cached = [await fake_redis.get(k) for k in keys if ":newest:" in k]
    assert all('"liked_by_me": true' not in str(c).lower() and "'liked_by_me': True" not in str(c) for c in cached)
    as_alice = (await client.get(f"{API}/comments", params=q, headers=alice)).json()["items"][0]
    assert as_alice["liked_by_me"] is False and as_alice["mine"] is True  # same cached page, her own overlay
    anonymous = (await client.get(f"{API}/comments", params=q)).json()["items"][0]
    assert anonymous["liked_by_me"] is False and anonymous["mine"] is False


async def test_a_new_comment_shows_up_at_once_despite_the_cache(client, make_user, article):
    _, fan = await make_user("fan@example.com")
    q = {"target_type": "article", "target_id": article["id"]}
    assert (await client.get(f"{API}/comments", params=q)).json()["total"] == 0  # warms the cache
    await _comment(client, fan, article["id"], "Instantly visible")
    assert (await client.get(f"{API}/comments", params=q)).json()["total"] == 1


async def test_likes_are_idempotent_and_reversible(client, make_user, article):
    _, alice = await make_user("alice@example.com")
    _, bob = await make_user("bob@example.com")
    comment = (await _comment(client, alice, article["id"], "Like me")).json()
    url = f"{API}/comments/{comment['id']}/like"
    assert (await client.put(url, headers={})).status_code == 401
    assert (await client.put(url, headers=bob)).json()["like_count"] == 1
    assert (await client.put(url, headers=bob)).json()["like_count"] == 1  # a second tap changes nothing
    assert (await client.put(url, headers=alice)).json()["like_count"] == 2
    assert (await client.delete(url, headers=bob)).json()["like_count"] == 1
    assert (await client.delete(url, headers=bob)).json()["like_count"] == 1
    assert (await client.put(f"{API}/comments/999999/like", headers=bob)).status_code == 404


# -- reports & moderation -----------------------------------------------------------------------------


async def test_reports_are_idempotent_and_you_cannot_report_yourself(client, make_user, article):
    _, author = await make_user("author@example.com")
    _, reporter = await make_user("reporter@example.com")
    comment = (await _comment(client, author, article["id"], "Borderline")).json()
    url = f"{API}/comments/{comment['id']}/report"
    assert (await client.post(url, json={"reason": "spam"}, headers=author)).status_code == 422
    assert (await client.post(url, json={"reason": "spam"}, headers={})).status_code == 401
    assert (await client.post(url, json={"reason": "spam"}, headers=reporter)).status_code == 204
    assert (await client.post(url, json={"reason": "spam"}, headers=reporter)).status_code == 204
    page = (await client.get(f"{API}/comments", params={"target_type": "article", "target_id": article["id"]})).json()
    assert page["total"] == 1  # one report does not hide anything


async def test_enough_independent_reports_hide_a_comment_until_a_moderator_decides(client, make_user, article):
    _, author = await make_user("author@example.com")
    _, moderator = await make_user("mod@example.com", UserRole.EDITOR)
    comment = (await _comment(client, author, article["id"], "Awful thing")).json()
    q = {"target_type": "article", "target_id": article["id"]}
    for i in range(settings.comment_auto_hide_reports):
        _, reporter = await make_user(f"r{i}@example.com")
        await client.post(f"{API}/comments/{comment['id']}/report", json={"reason": "abuse"}, headers=reporter)
    assert (await client.get(f"{API}/comments", params=q)).json()["total"] == 0  # hidden pending review

    reports = (await client.get(f"{API}/moderation/reports", headers=moderator)).json()
    assert reports["total"] == settings.comment_auto_hide_reports
    assert reports["items"][0]["comment_body"] == "Awful thing" and reports["items"][0]["comment_status"] == "hidden"

    assert (await client.post(f"{API}/moderation/comments/{comment['id']}", json={"action": "restore"}, headers=moderator)).status_code == 204
    assert (await client.get(f"{API}/comments", params=q)).json()["total"] == 1
    assert (await client.get(f"{API}/moderation/reports", headers=moderator)).json()["total"] == 0  # dismissed
    dismissed = (await client.get(f"{API}/moderation/reports", params={"status": "dismissed"}, headers=moderator)).json()
    assert dismissed["total"] == settings.comment_auto_hide_reports

    assert (await client.post(f"{API}/moderation/comments/{comment['id']}", json={"action": "delete"}, headers=moderator)).status_code == 204
    assert (await client.get(f"{API}/comments", params=q)).json()["total"] == 0


async def test_moderation_is_for_editors_only(client, make_user, article):
    _, fan = await make_user("fan@example.com")
    _, author_role = await make_user("writer@example.com", UserRole.AUTHOR)
    comment = (await _comment(client, fan, article["id"], "Fine comment")).json()
    for headers in ({}, fan, author_role):
        assert (await client.get(f"{API}/moderation/reports", headers=headers)).status_code in (401, 403)
        assert (await client.post(f"{API}/moderation/comments/{comment['id']}", json={"action": "hide"}, headers=headers)).status_code in (401, 403)
    assert (await client.post(f"{API}/moderation/comments/{comment['id']}", json={"action": "explode"}, headers=fan)).status_code in (401, 403, 422)


async def test_a_moderator_can_delete_anyones_comment(client, make_user, article):
    _, author = await make_user("author@example.com")
    _, moderator = await make_user("mod@example.com", UserRole.ADMIN)
    comment = (await _comment(client, author, article["id"], "Take me down")).json()
    assert (await client.delete(f"{API}/comments/{comment['id']}", headers=moderator)).status_code == 204
    assert (await client.get(f"{API}/comments", params={"target_type": "article", "target_id": article["id"]})).json()["total"] == 0


# -- reactions ------------------------------------------------------------------------------------------


async def test_reactions_count_replace_and_remove(client, make_user, article, fake_redis):
    _, alice = await make_user("alice@example.com")
    _, bob = await make_user("bob@example.com")
    url = f"{API}/reactions/article/{article['id']}"
    empty = (await client.get(url)).json()
    ZERO = dict.fromkeys(("thumbs_up", "fire", "wow", "goal", "heart", "laugh", "clap"), 0)
    assert empty["counts"] == ZERO and empty["total"] == 0 and empty["mine"] is None
    assert (await client.put(url, json={"kind": "fire"}, headers={})).status_code == 401
    assert (await client.put(url, json={"kind": "fire"}, headers=alice)).json()["counts"]["fire"] == 1
    assert (await client.put(url, json={"kind": "fire"}, headers=alice)).json()["counts"]["fire"] == 1  # idempotent
    after_bob = (await client.put(url, json={"kind": "goal"}, headers=bob)).json()
    assert after_bob["counts"]["fire"] == 1 and after_bob["counts"]["goal"] == 1 and after_bob["mine"] == "goal"
    switched = (await client.put(url, json={"kind": "wow"}, headers=alice)).json()  # one reaction per user: replace
    assert switched["counts"] == {**ZERO, "wow": 1, "goal": 1} and switched["total"] == 2
    assert (await client.get(url, headers=alice)).json()["mine"] == "wow"
    assert (await client.get(url)).json()["mine"] is None  # the public count carries no viewer data
    removed = (await client.delete(url, headers=alice)).json()
    assert removed["counts"]["wow"] == 0 and removed["mine"] is None
    assert (await client.delete(url, headers=alice)).json()["total"] == 1  # removing twice is harmless
    assert await fake_redis.raw.exists("football:reactions:article:%d" % article["id"])  # served from the Redis hash


async def test_reaction_counts_rebuild_from_postgres_when_redis_forgets(client, make_user, article, fake_redis):
    _, alice = await make_user("alice@example.com")
    url = f"{API}/reactions/article/{article['id']}"
    await client.put(url, json={"kind": "thumbs_up"}, headers=alice)
    await fake_redis.raw.flushall()  # a Redis restart
    assert (await client.get(url)).json()["counts"]["thumbs_up"] == 1
    await fake_redis.raw.hset("football:reactions:article:%d" % article["id"], mapping={"_": 1, "thumbs_up": 99})  # drifted
    assert (await client.get(url)).json()["counts"]["thumbs_up"] == 99  # trusted until its TTL...
    assert 0 < await fake_redis.raw.ttl("football:reactions:article:%d" % article["id"]) <= 600  # ...which bounds the drift


async def test_reactions_validate_their_input(client, make_user, article, seeded_client, session_factory):
    _, fan = await make_user("fan@example.com")
    assert (await client.put(f"{API}/reactions/article/{article['id']}", json={"kind": "angry"}, headers=fan)).status_code == 422
    assert (await client.put(f"{API}/reactions/article/999999", json={"kind": "fire"}, headers=fan)).status_code == 404
    assert (await client.put(f"{API}/reactions/podcast/1", json={"kind": "fire"}, headers=fan)).status_code == 422
    match_id = await _match_id(session_factory)
    assert (await client.put(f"{API}/reactions/match/{match_id}", json={"kind": "goal"}, headers=fan)).json()["counts"]["goal"] == 1


async def test_reactions_survive_a_redis_outage(client, make_user, article, monkeypatch, fake_redis):
    _, fan = await make_user("fan@example.com")
    url = f"{API}/reactions/article/{article['id']}"
    await client.put(url, json={"kind": "fire"}, headers=fan)

    async def down(*a, **k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fake_redis.raw, "hgetall", down)
    monkeypatch.setattr(fake_redis.raw, "hincrby", down)
    assert (await client.get(url)).json()["counts"]["fire"] == 1  # straight from PostgreSQL


# -- polls -------------------------------------------------------------------------------------------------


def _poll(**over):
    return {"question": "Who will win the derby?", "kind": "question", "options": ["Red", "Blue"], **over}


async def test_only_editors_create_polls(client, make_user):
    _, fan = await make_user("fan@example.com")
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    assert (await client.post(f"{API}/editor/polls", json=_poll(), headers={})).status_code == 401
    assert (await client.post(f"{API}/editor/polls", json=_poll(), headers=fan)).status_code == 403
    assert (await client.post(f"{API}/editor/polls", json=_poll(), headers=author)).status_code == 403
    created = await client.post(f"{API}/editor/polls", json=_poll(), headers=editor)
    assert created.status_code == 201
    poll = created.json()
    assert poll["status"] == "open" and poll["total_votes"] == 0 and [o["label"] for o in poll["options"]] == ["Red", "Blue"]


@pytest.mark.parametrize(
    "override",
    [{"options": ["Only one"]}, {"options": []}, {"options": ["a", "b", "c", "d", "e", "f", "g"]}, {"options": ["Same", "same"]}, {"question": "Hi"}, {"match_id": 999999}, {"article_id": 999999}],
)
async def test_poll_validation(client, make_user, override):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    assert (await client.post(f"{API}/editor/polls", json=_poll(**override), headers=editor)).status_code == 422


async def test_a_match_poll_defaults_to_home_draw_away(seeded_client, make_user, session_factory):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    match_id = await _match_id(session_factory)
    poll = (await seeded_client.post(f"{API}/editor/polls", json={"question": "Who will win?", "kind": "match", "match_id": match_id}, headers=editor)).json()
    labels = [o["label"] for o in poll["options"]]
    assert len(labels) == 3 and labels[0].endswith("win") and labels[1] == "Draw" and labels[2].endswith("win")
    assert (await seeded_client.get(f"{API}/polls", params={"match_id": match_id})).json()[0]["id"] == poll["id"]


async def test_one_vote_per_person_and_results_update(client, make_user, fake_redis):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    _, alice = await make_user("alice@example.com")
    _, bob = await make_user("bob@example.com")
    _, cara = await make_user("cara@example.com")
    poll = (await client.post(f"{API}/editor/polls", json=_poll(), headers=editor)).json()
    red, blue = poll["options"][0]["id"], poll["options"][1]["id"]
    url = f"{API}/polls/{poll['id']}/vote"
    assert (await client.post(url, json={"option_id": red}, headers={})).status_code == 401
    first = (await client.post(url, json={"option_id": red}, headers=alice)).json()
    assert first["my_vote"] == red and first["total_votes"] == 1
    assert (await client.post(url, json={"option_id": blue}, headers=alice)).status_code == 409  # cannot vote twice, nor change
    await client.post(url, json={"option_id": red}, headers=bob)
    await client.post(url, json={"option_id": blue}, headers=cara)
    result = (await client.get(f"{API}/polls/{poll['id']}")).json()
    assert result["total_votes"] == 3 and result["my_vote"] is None  # the public view carries nobody's vote
    by_label = {o["label"]: o for o in result["options"]}
    assert by_label["Red"]["votes"] == 2 and by_label["Red"]["percent"] == 66.7 and by_label["Blue"]["percent"] == 33.3
    assert (await client.get(f"{API}/polls/{poll['id']}", headers=cara)).json()["my_vote"] == blue
    assert await fake_redis.raw.exists(f"football:poll:{poll['id']}:counts")


async def test_votes_for_other_polls_options_are_rejected(client, make_user):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    _, fan = await make_user("fan@example.com")
    a = (await client.post(f"{API}/editor/polls", json=_poll(), headers=editor)).json()
    b = (await client.post(f"{API}/editor/polls", json=_poll(question="Another question here"), headers=editor)).json()
    assert (await client.post(f"{API}/polls/{a['id']}/vote", json={"option_id": b["options"][0]["id"]}, headers=fan)).status_code == 422
    assert (await client.post(f"{API}/polls/999999/vote", json={"option_id": 1}, headers=fan)).status_code == 404


async def test_poll_counts_rebuild_from_the_database(client, make_user, fake_redis):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    _, fan = await make_user("fan@example.com")
    poll = (await client.post(f"{API}/editor/polls", json=_poll(), headers=editor)).json()
    await client.post(f"{API}/polls/{poll['id']}/vote", json={"option_id": poll["options"][0]["id"]}, headers=fan)
    await fake_redis.raw.flushall()
    assert (await client.get(f"{API}/polls/{poll['id']}")).json()["total_votes"] == 1


async def test_closing_a_poll_stops_voting_and_names_a_winner(client, make_user, monkeypatch):
    from app.api.v1 import community

    queued = []
    monkeypatch.setattr(community.notify_poll_results, "delay", lambda *a: queued.append(a))
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    _, fan = await make_user("fan@example.com")
    poll = (await client.post(f"{API}/editor/polls", json=_poll(), headers=editor)).json()
    await client.post(f"{API}/polls/{poll['id']}/vote", json={"option_id": poll["options"][1]["id"]}, headers=fan)
    assert (await client.post(f"{API}/editor/polls/{poll['id']}/close", headers=fan)).status_code == 403
    closed = (await client.post(f"{API}/editor/polls/{poll['id']}/close", headers=editor)).json()
    assert closed["status"] == "closed" and closed["winner_option_id"] == poll["options"][1]["id"]
    assert queued == [(poll["id"],)]
    await client.post(f"{API}/editor/polls/{poll['id']}/close", headers=editor)  # closing again is a no-op
    assert queued == [(poll["id"],)]
    _, late = await make_user("late@example.com")
    assert (await client.post(f"{API}/polls/{poll['id']}/vote", json={"option_id": poll["options"][0]["id"]}, headers=late)).status_code == 409


async def test_polls_close_themselves_when_their_time_is_up(client, make_user, session_factory, fake_redis):
    from app.models.community import Poll
    from app.services.community_service import PollService

    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    _, fan = await make_user("fan@example.com")
    soon = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    poll = (await client.post(f"{API}/editor/polls", json=_poll(closes_at=soon), headers=editor)).json()
    past = (await client.post(f"{API}/editor/polls", json=_poll(closes_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()), headers=editor))
    assert past.status_code == 422  # cannot create one that has already ended
    async with session_factory() as session:
        (await session.get(Poll, poll["id"])).closes_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        await session.commit()
    # voting is refused as soon as the time passes, before any task has run
    assert (await client.post(f"{API}/polls/{poll['id']}/vote", json={"option_id": poll["options"][0]["id"]}, headers=fan)).status_code == 409
    async with session_factory() as session:
        assert await PollService(session, fake_redis).close_due() == [poll["id"]]
    async with session_factory() as session:
        assert await PollService(session, fake_redis).close_due() == []  # idempotent
    assert (await client.get(f"{API}/polls/{poll['id']}")).json()["status"] == "closed"


async def test_list_filters_and_standalone(client, make_user, article):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    loose = (await client.post(f"{API}/editor/polls", json=_poll(), headers=editor)).json()
    attached = (await client.post(f"{API}/editor/polls", json=_poll(question="Transfer: will he sign?", kind="transfer", article_id=article["id"]), headers=editor)).json()
    assert [p["id"] for p in (await client.get(f"{API}/polls", params={"standalone": True})).json()] == [loose["id"]]
    assert [p["id"] for p in (await client.get(f"{API}/polls", params={"article_id": article["id"]})).json()] == [attached["id"]]
    assert (await client.delete(f"{API}/editor/polls/{loose['id']}", headers=editor)).status_code == 204
    assert (await client.get(f"{API}/polls/{loose['id']}")).status_code == 404


async def test_the_unique_constraint_is_the_real_guard_against_double_votes(client, make_user, session_factory):
    from sqlalchemy.exc import IntegrityError

    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    user, fan = await make_user("fan@example.com")
    poll = (await client.post(f"{API}/editor/polls", json=_poll(), headers=editor)).json()
    await client.post(f"{API}/polls/{poll['id']}/vote", json={"option_id": poll["options"][0]["id"]}, headers=fan)
    async with session_factory() as session:
        session.add(PollVote(poll_id=poll["id"], option_id=poll["options"][1]["id"], user_id=user.id))
        with pytest.raises(IntegrityError):
            await session.commit()

