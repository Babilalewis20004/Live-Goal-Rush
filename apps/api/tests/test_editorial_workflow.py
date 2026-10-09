"""Editorial workflow (AUTHOR -> review -> EDITOR approval -> publish), scheduled
publishing and revisions (Phase 6)."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.article import Article
from app.models.enums import ArticleStatus, UserRole
from app.models.revision import ArticleRevision
from app.services.article_service import ArticleService

API = "/api/v1"
E = f"{API}/editor/articles"


def _in(minutes: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def queued(monkeypatch):
    """Record the background jobs the editor API enqueues instead of sending them."""
    from app.api.v1 import editor as editor_module

    calls: list[tuple[str, tuple]] = []
    for task in (editor_module.dispatch_article_notifications, editor_module.notify_editorial):
        monkeypatch.setattr(task, "delay", lambda *a, _n=task.name, **k: calls.append((_n.rsplit(".", 1)[-1], a)))
    return calls


async def _draft(client, headers, title="Draft piece", **extra):
    r = await client.post(E, json={"title": title, "content": f"<p>{title} body</p>", **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# -- roles & transitions ---------------------------------------------------------------------------


async def test_an_author_writes_and_submits_but_can_never_publish(client, make_user):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    article = await _draft(client, author)
    assert article["status"] == "draft"
    for action in ("publish", "archive"):  # (unpublish on a draft is simply a no-op)
        assert (await client.post(f"{E}/{article['id']}/{action}", headers=author)).status_code == 403, action
    assert (await client.post(f"{E}/{article['id']}/schedule", json={"publish_at": _in(60)}, headers=author)).status_code == 403
    assert (await client.post(f"{E}/{article['id']}/approve", headers=author)).status_code == 403
    r = await client.post(E, json={"title": "Straight to live", "content": "<p>x</p>", "status": "published"}, headers=author)
    assert r.status_code == 403
    r = await client.post(E, json={"title": "Sneaky schedule", "content": "<p>x</p>", "status": "scheduled", "publish_at": _in(60)}, headers=author)
    assert r.status_code == 403
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 404


async def test_the_full_review_flow(client, make_user, queued):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, author, "Reviewed story")

    submitted = (await client.post(f"{E}/{article['id']}/submit", headers=author)).json()
    assert submitted["status"] == "in_review"
    assert ("notify_editorial", (article["id"], "submitted")) in queued

    # the editor's queue contains it; the author can no longer edit it
    queue = (await client.get(E, params={"status": "in_review"}, headers=editor)).json()
    assert [a["title"] for a in queue["items"]] == ["Reviewed story"]
    assert (await client.patch(f"{E}/{article['id']}", json={"title": "Changed"}, headers=author)).status_code == 403

    approved = (await client.post(f"{E}/{article['id']}/approve", headers=editor)).json()
    assert approved["status"] == "published" and approved["published_at"]
    assert ("dispatch_article_notifications", (article["id"],)) in queued
    assert ("notify_editorial", (article["id"], "published")) in queued
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 200
    # the author can still see it, but not unpublish it
    assert (await client.get(f"{E}/{article['id']}", headers=author)).status_code == 200
    assert (await client.post(f"{E}/{article['id']}/unpublish", headers=author)).status_code == 403


async def test_reject_sends_it_back_with_a_note(client, make_user, queued):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, author)
    await client.post(f"{E}/{article['id']}/submit", headers=author)
    rejected = (await client.post(f"{E}/{article['id']}/reject", json={"note": "Needs a source for the quote."}, headers=editor)).json()
    assert rejected["status"] == "draft" and rejected["review_note"] == "Needs a source for the quote."
    assert ("notify_editorial", (article["id"], "rejected")) in queued
    # the author can edit again and resubmit; the note clears
    assert (await client.patch(f"{E}/{article['id']}", json={"title": "Better title"}, headers=author)).status_code == 200
    again = (await client.post(f"{E}/{article['id']}/submit", headers=author)).json()
    assert again["status"] == "in_review" and again["review_note"] is None


async def test_an_author_can_withdraw_but_only_their_own(client, make_user):
    _, alice = await make_user("alice@example.com", UserRole.AUTHOR)
    _, bob = await make_user("bob@example.com", UserRole.AUTHOR)
    article = await _draft(client, alice)
    await client.post(f"{E}/{article['id']}/submit", headers=alice)
    assert (await client.post(f"{E}/{article['id']}/withdraw", headers=bob)).status_code == 403
    assert (await client.post(f"{E}/{article['id']}/withdraw", headers=alice)).json()["status"] == "draft"


async def test_nobody_sees_someone_elses_draft_except_an_admin(client, make_user):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    _, admin = await make_user("admin@example.com", UserRole.ADMIN)
    _, other = await make_user("other@example.com", UserRole.AUTHOR)
    article = await _draft(client, author)
    assert (await client.get(f"{E}/{article['id']}", headers=editor)).status_code == 403
    assert (await client.get(f"{E}/{article['id']}", headers=other)).status_code == 403
    assert (await client.get(E, headers=editor)).json()["total"] == 0
    assert (await client.get(E, headers=admin)).json()["total"] == 1
    assert (await client.get(f"{E}/{article['id']}/revisions", headers=editor)).status_code == 403


async def test_an_editor_can_edit_and_publish_what_is_in_review(client, make_user):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, author)
    await client.post(f"{E}/{article['id']}/submit", headers=author)
    fixed = await client.patch(f"{E}/{article['id']}", json={"title": "Sub-edited headline"}, headers=editor)
    assert fixed.status_code == 200 and fixed.json()["title"] == "Sub-edited headline"
    assert fixed.json()["author_id"] == article["author_id"]  # still the author's piece


async def test_authors_cannot_feature_articles(client, make_user):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    created = await client.post(E, json={"title": "Wants the spotlight", "content": "<p>x</p>", "is_featured": True}, headers=author)
    assert created.json()["is_featured"] is False  # ignored, not an error: they cannot ask for it
    article = created.json()
    assert (await client.patch(f"{E}/{article['id']}", json={"is_featured": True}, headers=author)).status_code == 403


async def test_submitting_needs_content_and_only_drafts_can_be_submitted(client, make_user):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    empty = (await client.post(E, json={"title": "Nothing yet"}, headers=author)).json()
    assert (await client.post(f"{E}/{empty['id']}/submit", headers=author)).status_code == 422
    article = await _draft(client, author)
    await client.post(f"{E}/{article['id']}/submit", headers=author)
    assert (await client.post(f"{E}/{article['id']}/submit", headers=author)).status_code in (200, 422)  # idempotent or refused, never a crash


async def test_authors_can_delete_only_their_own_drafts(client, make_user):
    _, alice = await make_user("alice@example.com", UserRole.AUTHOR)
    _, bob = await make_user("bob@example.com", UserRole.AUTHOR)
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    mine = await _draft(client, alice, "Mine")
    assert (await client.delete(f"{E}/{mine['id']}", headers=bob)).status_code == 403
    submitted = await _draft(client, alice, "In review")
    await client.post(f"{E}/{submitted['id']}/submit", headers=alice)
    assert (await client.delete(f"{E}/{submitted['id']}", headers=alice)).status_code == 403
    assert (await client.delete(f"{E}/{mine['id']}", headers=alice)).status_code == 204
    assert (await client.delete(f"{E}/{submitted['id']}", headers=editor)).status_code == 204


async def test_a_normal_user_still_has_no_editorial_access(client, make_user):
    _, fan = await make_user("fan@example.com")
    assert (await client.get(E, headers=fan)).status_code == 403
    assert (await client.post(f"{E}", json={"title": "Nope"}, headers=fan)).status_code == 403


# -- scheduling -----------------------------------------------------------------------------------------


async def test_scheduling_validates_the_times(client, make_user):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, editor)
    url = f"{E}/{article['id']}/schedule"
    assert (await client.post(url, json={"publish_at": _in(-5)}, headers=editor)).status_code == 422  # in the past
    assert (await client.post(url, json={"publish_at": _in(60), "unpublish_at": _in(30)}, headers=editor)).status_code == 422  # ends before it starts
    ok = (await client.post(url, json={"publish_at": _in(60), "unpublish_at": _in(120)}, headers=editor)).json()
    assert ok["status"] == "scheduled" and ok["publish_at"] and ok["unpublish_at"]
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 404  # not yet public
    no_content = (await client.post(E, json={"title": "Empty draft"}, headers=editor)).json()
    assert (await client.post(f"{E}/{no_content['id']}/schedule", json={"publish_at": _in(60)}, headers=editor)).status_code == 422


async def test_approve_with_a_time_schedules_instead_of_publishing(client, make_user, queued):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, author)
    await client.post(f"{E}/{article['id']}/submit", headers=author)
    result = (await client.post(f"{E}/{article['id']}/approve", json={"publish_at": _in(90)}, headers=editor)).json()
    assert result["status"] == "scheduled"
    assert ("notify_editorial", (article["id"], "scheduled")) in queued
    assert not any(name == "dispatch_article_notifications" for name, _ in queued)  # nothing goes out until it is live


async def _force_due(session_factory, article_id, *, publish_at=None, unpublish_at=None):
    async with session_factory() as session:
        article = await session.get(Article, article_id)
        if publish_at:
            article.publish_at = publish_at
        if unpublish_at:
            article.unpublish_at = unpublish_at
        await session.commit()


async def test_the_scheduler_publishes_due_articles_exactly_once(client, make_user, session_factory, fake_redis):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    due = await _draft(client, editor, "Due now")
    later = await _draft(client, editor, "Due later")
    await client.post(f"{E}/{due['id']}/schedule", json={"publish_at": _in(30)}, headers=editor)
    await client.post(f"{E}/{later['id']}/schedule", json={"publish_at": _in(300)}, headers=editor)

    async with session_factory() as session:
        assert await ArticleService(session, fake_redis).run_schedule() == ([], [])  # nothing due yet
    scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=2)
    await _force_due(session_factory, due["id"], publish_at=scheduled_for)

    async with session_factory() as session:
        published, archived = await ArticleService(session, fake_redis).run_schedule()
    assert published == [due["id"]] and archived == []
    live = (await client.get(f"{API}/articles/{due['slug']}")).json()
    assert live["published_at"].startswith(scheduled_for.strftime("%Y-%m-%dT%H:%M"))  # goes out as of its slot
    assert (await client.get(f"{API}/articles/{later['slug']}")).status_code == 404

    async with session_factory() as session:  # running again changes nothing
        assert await ArticleService(session, fake_redis).run_schedule() == ([], [])
    detail = (await client.get(f"{E}/{due['id']}", headers=editor)).json()
    assert detail["status"] == "published" and detail["publish_at"] is None


async def test_concurrent_scheduler_runs_never_double_publish(client, make_user, session_factory, fake_redis):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    ids = []
    for i in range(4):
        article = await _draft(client, editor, f"Concurrent {i}")
        await client.post(f"{E}/{article['id']}/schedule", json={"publish_at": _in(30)}, headers=editor)
        await _force_due(session_factory, article["id"], publish_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        ids.append(article["id"])

    async def run_once():
        async with session_factory() as session:
            return await ArticleService(session, fake_redis).run_schedule()

    results = await asyncio.gather(run_once(), run_once(), run_once())
    published = [i for pub, _ in results for i in pub]
    assert sorted(published) == sorted(ids)  # each claimed by exactly one run
    async with session_factory() as session:
        versions = (await session.execute(select(ArticleRevision.article_id).where(ArticleRevision.action == "SCHEDULED"))).scalars().all()
    assert sorted(versions) == sorted(ids)  # and each got exactly one system revision


async def test_the_scheduler_archives_expired_articles_and_reads_hide_them_immediately(client, make_user, session_factory, fake_redis):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, editor, "Limited time")
    await client.post(f"{E}/{article['id']}/approve", json={"unpublish_at": _in(30)}, headers=editor)
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 200
    await _force_due(session_factory, article["id"], unpublish_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    # Hidden the moment the time passes, even before the task has run...
    assert (await client.get(f"{API}/articles", params={"page_size": 5})).json()["total"] == 0
    # ...and the task then archives it.
    async with session_factory() as session:
        published, archived = await ArticleService(session, fake_redis).run_schedule()
    assert archived == [article["id"]] and published == []
    assert (await client.get(f"{E}/{article['id']}", headers=editor)).json()["status"] == "archived"


async def test_unpublish_cancels_a_schedule(client, make_user, session_factory, fake_redis):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, editor)
    await client.post(f"{E}/{article['id']}/schedule", json={"publish_at": _in(30)}, headers=editor)
    cancelled = (await client.post(f"{E}/{article['id']}/unpublish", headers=editor)).json()
    assert cancelled["status"] == "draft" and cancelled["publish_at"] is None
    await _force_due(session_factory, article["id"], publish_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    async with session_factory() as session:
        assert await ArticleService(session, fake_redis).run_schedule() == ([], [])


async def test_publishing_by_the_scheduler_invalidates_cached_lists(client, make_user, session_factory, fake_redis):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, editor, "Cached away")
    await client.post(f"{E}/{article['id']}/schedule", json={"publish_at": _in(30)}, headers=editor)
    assert (await client.get(f"{API}/articles")).json()["total"] == 0  # warms the cache
    await _force_due(session_factory, article["id"], publish_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    async with session_factory() as session:
        await ArticleService(session, fake_redis).run_schedule()
    assert (await client.get(f"{API}/articles")).json()["total"] == 1


# -- revisions ------------------------------------------------------------------------------------------------


async def test_every_save_adds_a_revision_that_names_what_changed(client, make_user):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, editor, "First title", tags=["Injury"])
    await client.patch(f"{E}/{article['id']}", json={"title": "Second title"}, headers=editor)
    await client.patch(f"{E}/{article['id']}", json={"title": "Second title"}, headers=editor)  # no actual change
    await client.patch(f"{E}/{article['id']}", json={"content": "<p>Rewritten body</p>", "tags": ["Injury", "Transfer"]}, headers=editor)
    revisions = (await client.get(f"{E}/{article['id']}/revisions", headers=editor)).json()
    assert [r["version"] for r in revisions] == [3, 2, 1]  # newest first; the no-op saved nothing
    assert [r["action"] for r in revisions] == ["update", "update", "create"]
    assert revisions[1]["changes"] == ["title"]
    assert set(revisions[0]["changes"]) == {"content", "tags"}
    assert revisions[0]["editor_name"] == "Editor"
    assert "title" in revisions[2]["changes"]  # a creation lists everything


async def test_a_revision_holds_the_whole_state_at_that_moment(client, make_user):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, editor, "Original")
    await client.patch(f"{E}/{article['id']}", json={"title": "Edited", "content": "<p>New</p>"}, headers=editor)
    v1 = (await client.get(f"{E}/{article['id']}/revisions/1", headers=editor)).json()
    assert v1["snapshot"]["title"] == "Original" and "Original body" in v1["snapshot"]["content"]
    assert v1["snapshot"]["status"] == "draft"
    assert (await client.get(f"{E}/{article['id']}/revisions/99", headers=editor)).status_code == 404


async def test_status_changes_are_revisions_too(client, make_user):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, editor)
    await client.post(f"{E}/{article['id']}/publish", headers=editor)
    revisions = (await client.get(f"{E}/{article['id']}/revisions", headers=editor)).json()
    assert revisions[0]["action"] == "status" and "status" in revisions[0]["changes"]


async def test_compare_shows_field_changes_and_a_paragraph_diff(client, make_user):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await client.post(E, json={"title": "Diffable", "content": "<h2>Head</h2><p>Keep this</p><p>Remove this</p>"}, headers=editor)
    article = article.json()
    await client.patch(f"{E}/{article['id']}", json={"title": "Diffable v2", "content": "<h2>Head</h2><p>Keep this</p><p>Add this</p>"}, headers=editor)
    diff = (await client.get(f"{E}/{article['id']}/revisions/compare", params={"from_version": 1, "to_version": 2}, headers=editor)).json()
    fields = {c["field"]: c for c in diff["changes"]}
    assert fields["title"]["before"] == "Diffable" and fields["title"]["after"] == "Diffable v2"
    assert "content" in fields
    lines = {(d["kind"], d["text"]) for d in diff["content_diff"]}
    assert ("del", "Remove this") in lines and ("add", "Add this") in lines
    assert ("ctx", "Keep this") in lines
    assert (await client.get(f"{E}/{article['id']}/revisions/compare", params={"from_version": 1, "to_version": 9}, headers=editor)).status_code == 404


async def test_restore_brings_content_back_as_a_new_revision_without_touching_publication(client, make_user):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, editor, "Restorable", tags=["One"])
    await client.post(f"{E}/{article['id']}/publish", headers=editor)
    await client.patch(f"{E}/{article['id']}", json={"title": "Vandalised", "content": "<p>Oops</p>", "tags": ["Two"]}, headers=editor)
    assert (await client.get(f"{API}/articles/{article['slug']}")).json()["title"] == "Vandalised"

    restored = (await client.post(f"{E}/{article['id']}/revisions/1/restore", headers=editor)).json()
    assert restored["title"] == "Restorable" and "Restorable body" in restored["content"]
    assert [t["name"] for t in restored["tags"]] == ["One"]
    assert restored["status"] == "published"  # restoring text is not publishing or unpublishing
    assert (await client.get(f"{API}/articles/{article['slug']}")).json()["title"] == "Restorable"  # live and cache refreshed
    revisions = (await client.get(f"{E}/{article['id']}/revisions", headers=editor)).json()
    assert revisions[0]["action"] == "restore" and len(revisions) == 4  # history is never rewritten


async def test_restore_tolerates_entities_deleted_since(client, make_user, session_factory):
    from app.models.team import Team

    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    async with session_factory() as session:
        team = Team(provider_id="temp-team", name="Temporary FC")
        session.add(team)
        await session.commit()
        team_id = team.id
    article = await _draft(client, editor, "Linked", team_ids=[team_id])
    await client.patch(f"{E}/{article['id']}", json={"team_ids": []}, headers=editor)
    async with session_factory() as session:
        await session.delete(await session.get(Team, team_id))
        await session.commit()
    restored = await client.post(f"{E}/{article['id']}/revisions/1/restore", headers=editor)
    assert restored.status_code == 200 and restored.json()["teams"] == []


async def test_authors_can_restore_only_their_own_drafts(client, make_user):
    _, author = await make_user("author@example.com", UserRole.AUTHOR)
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, author, "Mine")
    await client.patch(f"{E}/{article['id']}", json={"title": "Edited"}, headers=author)
    assert (await client.post(f"{E}/{article['id']}/revisions/1/restore", headers=author)).status_code == 200
    await client.post(f"{E}/{article['id']}/submit", headers=author)
    assert (await client.post(f"{E}/{article['id']}/revisions/1/restore", headers=author)).status_code == 403  # in review: hands off
    assert (await client.post(f"{E}/{article['id']}/revisions/1/restore", headers=editor)).status_code == 200


async def test_revisions_are_sanitised_on_restore(client, make_user, session_factory):
    _, editor = await make_user("editor@example.com", UserRole.EDITOR)
    article = await _draft(client, editor)
    async with session_factory() as session:  # a hostile snapshot, as if written by a bug or by hand
        revision = (await session.execute(select(ArticleRevision).where(ArticleRevision.article_id == article["id"]))).scalar_one()
        revision.snapshot = {**revision.snapshot, "content": "<p>ok</p><script>alert(1)</script>"}
        await session.commit()
    restored = (await client.post(f"{E}/{article['id']}/revisions/1/restore", headers=editor)).json()
    assert "<script" not in restored["content"] and "ok" in restored["content"]
