"""Administrator API and audit trail (Phase 7 §45-46)."""

import pytest
from sqlalchemy import select

from app.models.enums import UserRole
from app.models.operations import AuditLog, FailedJob
from app.models.user import User

ADMIN_GETS = ["/admin/users", "/admin/users/1", "/admin/audit-log", "/admin/failed-jobs", "/admin/system"]


@pytest.mark.parametrize("path", ADMIN_GETS)
async def test_admin_endpoints_require_the_admin_role_on_the_server(client, make_user, path):
    assert (await client.get(f"/api/v1{path}")).status_code == 401
    for role in (UserRole.USER, UserRole.AUTHOR, UserRole.EDITOR):
        _u, headers = await make_user(f"{role.value}-{abs(hash(path))}@example.com", role)
        assert (await client.get(f"/api/v1{path}", headers=headers)).status_code == 403, role
    _a, admin = await make_user(f"admin-{abs(hash(path))}@example.com", UserRole.ADMIN)
    assert (await client.get(f"/api/v1{path}", headers=admin)).status_code in (200, 404)  # 404: no user #1 in some orders


async def test_resolving_a_failed_job_is_admin_only(client, make_user, session_factory):
    async with session_factory() as db:
        db.add(FailedJob(task_name="t", error_type="E", classification="permanent"))
        await db.commit()
    _u, user = await make_user("u@example.com")
    _e, editor = await make_user("e@example.com", UserRole.EDITOR)
    assert (await client.post("/api/v1/admin/failed-jobs/1/resolve", json={}, headers=user)).status_code == 403
    assert (await client.post("/api/v1/admin/failed-jobs/1/resolve", json={}, headers=editor)).status_code == 403
    async with session_factory() as db:
        assert (await db.scalar(select(FailedJob.resolved_at))) is None


async def test_users_can_be_searched_by_email_or_name_and_filtered(client, make_user):
    _a, admin = await make_user("boss@example.com", UserRole.ADMIN)
    await make_user("alice.smith@example.com")
    await make_user("bob@example.com", UserRole.EDITOR)
    found = (await client.get("/api/v1/admin/users", params={"q": "ALICE"}, headers=admin)).json()
    assert [u["email"] for u in found["items"]] == ["alice.smith@example.com"]
    editors = (await client.get("/api/v1/admin/users", params={"role": "editor"}, headers=admin)).json()
    assert [u["email"] for u in editors["items"]] == ["bob@example.com"]
    wildcard = (await client.get("/api/v1/admin/users", params={"q": "%"}, headers=admin)).json()
    assert wildcard["total"] == 0  # LIKE wildcards in the search box are literal


async def test_user_detail_shows_subscription_entitlements_and_never_credentials(client, make_user, session_factory):
    import json, time
    from app.core.config import settings
    from app.services.billing.providers import sign_payload

    _a, admin = await make_user("boss@example.com", UserRole.ADMIN)
    user, _h = await make_user("payer@example.com")
    payload = json.dumps({"id": "e1", "created": int(time.time()), "type": "subscription.activated", "data": {"user_id": user.id, "plan_code": "premium_monthly", "subscription_id": "sub_1", "customer_id": "cus_1", "period_end": "2099-01-01T00:00:00+00:00"}}).encode()
    await client.post("/api/v1/billing/webhook", content=payload, headers={"X-Signature": sign_payload(payload, settings.billing_webhook_secret), "Content-Type": "application/json"})
    detail = (await client.get(f"/api/v1/admin/users/{user.id}", headers=admin)).json()
    assert detail["subscription_status"] == "active" and detail["subscriptions"][0]["plan"] == "premium_monthly"
    assert detail["entitlements"]
    flat = json.dumps(detail)
    for secret in ("hashed_password", "cus_1", "sub_1", "$2b$"):
        assert secret not in flat


async def test_the_audit_log_records_moderation_actions_with_actor_target_and_reason(client, make_user, session_factory):
    admin_user, admin = await make_user("boss@example.com", UserRole.ADMIN)
    target, _ = await make_user("troll@example.com")
    resp = await client.post(f"/api/v1/moderation/users/{target.id}/suspend", json={"reason": "spam in comments"}, headers=admin)
    assert resp.status_code == 204
    await client.post(f"/api/v1/moderation/users/{target.id}/unsuspend", headers=admin)

    log = (await client.get("/api/v1/admin/audit-log", headers=admin)).json()
    actions = [e["action"] for e in log["items"]]
    assert actions[:2] == ["user.unsuspend", "user.suspend"]  # newest first
    suspend = log["items"][1]
    assert suspend["actor_id"] == admin_user.id and suspend["target_type"] == "user" and suspend["target_id"] == str(target.id)
    assert suspend["reason"] == "spam in comments"
    assert suspend["created_at"]


async def test_audit_log_can_be_filtered(client, make_user):
    _a, admin = await make_user("boss@example.com", UserRole.ADMIN)
    t1, _ = await make_user("t1@example.com")
    t2, _ = await make_user("t2@example.com")
    for t in (t1, t2):
        await client.post(f"/api/v1/moderation/users/{t.id}/suspend", json={"reason": "x"}, headers=admin)
    by_target = (await client.get("/api/v1/admin/audit-log", params={"target_type": "user", "target_id": str(t1.id)}, headers=admin)).json()
    assert by_target["total"] == 1
    by_action = (await client.get("/api/v1/admin/audit-log", params={"action": "user.suspend"}, headers=admin)).json()
    assert by_action["total"] == 2


async def test_a_failed_action_leaves_no_audit_entry(client, make_user, session_factory):
    _a, admin = await make_user("boss@example.com", UserRole.ADMIN)
    resp = await client.post("/api/v1/moderation/users/999/suspend", json={"reason": "x"}, headers=admin)
    assert resp.status_code == 404
    async with session_factory() as db:
        assert (await db.scalar(select(AuditLog.id))) is None


async def test_comment_moderation_is_audited(client, make_user, session_factory):
    editor, headers = await make_user("ed@example.com", UserRole.EDITOR)
    author, _author_headers = await make_user("writer@example.com")
    from app.models.community import Comment
    from app.models.enums import CommentStatus, CommentTarget
    async with session_factory() as db:
        db.add(Comment(user_id=author.id, target_type=CommentTarget.MATCH, target_id=1, body="rude", status=CommentStatus.VISIBLE))
        await db.commit()
    assert (await client.post("/api/v1/moderation/comments/1", json={"action": "hide"}, headers=headers)).status_code == 204
    async with session_factory() as db:
        entry = await db.scalar(select(AuditLog).where(AuditLog.action == "comment.hide"))
    assert entry.actor_id == editor.id and entry.target_id == "1" and entry.details == {"author_id": author.id}


async def test_the_cli_role_change_is_audited_without_exposing_an_email(session_factory, make_user):
    from app import cli

    user, _ = await make_user("promote@example.com")
    cli.AsyncSessionLocal = session_factory  # run the operator command against the test database
    assert await cli.set_role("Promote@Example.com", UserRole.EDITOR)
    async with session_factory() as db:
        assert (await db.get(User, user.id)).role == UserRole.EDITOR
        entry = await db.scalar(select(AuditLog))
    assert entry.action == "user.role_change" and entry.actor_label == "cli" and entry.actor_id is None
    assert entry.details == {"from": "user", "to": "editor"}
    assert "promote@example.com" not in (entry.actor_label + str(entry.details) + entry.target_id)


async def test_audit_details_never_store_secrets(session_factory):
    from app.services import audit_service

    async with session_factory() as db:
        audit_service.record(db, action="x", target_type="user", target_id=1, actor_label="cli", details={"password": "p", "token": "t", "email": "e@x.com", "role": "admin"})
        await db.commit()
        entry = await db.scalar(select(AuditLog))
    assert entry.details == {"role": "admin"}


async def test_audit_entries_survive_the_actors_erasure(client, make_user, session_factory):
    admin_user, admin = await make_user("boss@example.com", UserRole.ADMIN)
    target, _ = await make_user("t@example.com")
    await client.post(f"/api/v1/moderation/users/{target.id}/suspend", json={"reason": "x"}, headers=admin)
    async with session_factory() as db:
        row = await db.get(User, admin_user.id)
        await db.delete(row)  # the actor's row is removed entirely (e.g. an operator purge)
        await db.commit()
        entry = await db.scalar(select(AuditLog).where(AuditLog.action == "user.suspend"))
    assert entry is not None and entry.actor_id is None and entry.actor_label.startswith("user:")


async def test_system_status_reports_dependencies_queue_and_failures(client, make_user, session_factory, fake_redis):
    async with session_factory() as db:
        db.add(FailedJob(task_name="app.worker.tasks.sync_team", error_type="E", classification="permanent"))
        await db.commit()
    await fake_redis.raw.rpush("football", "job1", "job2")
    _a, admin = await make_user("boss@example.com", UserRole.ADMIN)
    status = (await client.get("/api/v1/admin/system", headers=admin)).json()
    assert status["database"] == "ok" and status["redis"] == "ok"
    assert status["queue_length"] == 2
    assert status["unresolved_failed_jobs"] == 1
    assert status["version"]
    assert set(status["db_pool"]) == {"size", "checked_out", "overflow"}
    assert "live_matches_not_synced_for_5_minutes" in status["data_freshness"]


async def test_failed_jobs_can_be_listed_filtered_and_resolved_with_an_audit_trail(client, make_user, session_factory):
    async with session_factory() as db:
        db.add_all(
            [
                FailedJob(task_name="app.worker.tasks.sync_team", error_type="HTTPStatusError", classification="temporary", entity="team:5", retries=3, occurrences=4),
                FailedJob(task_name="app.worker.analytics_tasks.generate_predictions", error_type="KeyError", classification="validation"),
            ]
        )
        await db.commit()
    admin_user, admin = await make_user("boss@example.com", UserRole.ADMIN)
    listing = (await client.get("/api/v1/admin/failed-jobs", headers=admin)).json()
    assert listing["total"] == 2
    team_job = next(j for j in listing["items"] if j["entity"] == "team:5")
    assert team_job["retries"] == 3 and team_job["occurrences"] == 4 and team_job["classification"] == "temporary"
    only = (await client.get("/api/v1/admin/failed-jobs", params={"task": "app.worker.tasks.sync_team"}, headers=admin)).json()
    assert only["total"] == 1

    assert (await client.post(f"/api/v1/admin/failed-jobs/{team_job['id']}/resolve", json={"note": "provider recovered"}, headers=admin)).status_code == 204
    assert (await client.get("/api/v1/admin/failed-jobs", headers=admin)).json()["total"] == 1
    resolved = (await client.get("/api/v1/admin/failed-jobs", params={"resolved": "true"}, headers=admin)).json()
    assert resolved["items"][0]["resolved_at"]
    async with session_factory() as db:
        entry = await db.scalar(select(AuditLog).where(AuditLog.action == "failed_job.resolve"))
    assert entry.actor_id == admin_user.id and entry.reason == "provider recovered"
    assert (await client.post("/api/v1/admin/failed-jobs/9999/resolve", json={}, headers=admin)).status_code == 404
