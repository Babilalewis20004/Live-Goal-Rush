"""Account deletion and data export (Phase 7 §42-44)."""

import json

import pytest
from sqlalchemy import func, select

from app.models.billing import Subscription
from app.models.community import Comment, CommentLike, PollVote, Reaction
from app.models.device import Device
from app.models.enums import CommentStatus, CommentTarget, DevicePlatform, ReactionKind, ReactionTarget, UserRole
from app.models.favourite import FavouriteTeam
from app.models.operations import AuditLog
from app.models.session import RefreshToken
from app.models.user import User

API = "/api/v1"
PASSWORD = "Sup3rSecret!"


async def _register(client, email="leaver@example.com"):
    resp = await client.post(
        f"{API}/auth/register",
        json={"email": email, "password": PASSWORD, "password_confirm": PASSWORD, "display_name": "Leaver"},
        headers={"X-Client": "mobile"},
    )
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['tokens']['access_token']}"}, body["tokens"]["refresh_token"]


async def _populate(session_factory, user_id, other_id):
    """Everything a person can leave behind."""
    from app.models.team import Team

    async with session_factory() as db:
        team = Team(name="Arsenal", short_name="ARS", provider_id="t-1")
        db.add(team)
        await db.flush()
        db.add(FavouriteTeam(user_id=user_id, team_id=team.id))
        db.add(Device(user_id=user_id, platform=DevicePlatform.EXPO_IOS, expo_push_token="ExponentPushToken[secret]"))
        db.add(Comment(user_id=user_id, target_type=CommentTarget.MATCH, target_id=1, body="my private opinion", status=CommentStatus.VISIBLE))
        db.add(Comment(user_id=other_id, target_type=CommentTarget.MATCH, target_id=1, body="someone else's comment", status=CommentStatus.VISIBLE))
        db.add(Reaction(user_id=user_id, target_type=ReactionTarget.ARTICLE, target_id=5, kind=ReactionKind.THUMBS_UP))
        await db.commit()


async def test_export_contains_the_users_own_data_and_nothing_else(client, make_user, session_factory):
    uid, headers, _ = await _register(client)
    other, _ = await make_user("other@example.com")
    await _populate(session_factory, uid, other.id)

    resp = await client.get(f"{API}/users/me/export", headers=headers)
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["cache-control"] == "no-store"
    data = resp.json()
    assert data["account"]["email"] == "leaver@example.com" and data["account"]["display_name"] == "Leaver"
    assert [c["body"] for c in data["comments"]] == ["my private opinion"]
    assert len(data["favourites"]["teams"]) == 1 and len(data["devices"]) == 1 and len(data["reactions"]) == 1

    flat = json.dumps(data)
    for forbidden in ("hashed_password", "$2b$", "ExponentPushToken", "other@example.com", "someone else's comment", "token_hash", "ip_address"):
        assert forbidden not in flat


async def test_export_requires_authentication(client):
    assert (await client.get(f"{API}/users/me/export")).status_code == 401


async def test_export_is_rate_limited(client, make_user):
    _u, headers = await make_user("busy@example.com")
    codes = [(await client.get(f"{API}/users/me/export", headers=headers)).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]


async def test_export_never_includes_payment_processor_identifiers(client, make_user, session_factory):
    from datetime import datetime, timedelta, timezone

    from app.models.billing import SubscriptionPlan
    from app.models.enums import SubscriptionStatus

    user, headers = await make_user("paying@example.com")
    async with session_factory() as db:
        plan = SubscriptionPlan(code="premium_monthly", name="Premium", interval="month", price_minor=499, currency="GBP", entitlements=["extended_history"])
        db.add(plan)
        await db.flush()
        db.add(Subscription(user_id=user.id, plan_id=plan.id, status=SubscriptionStatus.ACTIVE, provider="stripe", provider_subscription_id="sub_SECRET", provider_customer_id="cus_SECRET", current_period_end=datetime.now(timezone.utc) + timedelta(days=5)))
        await db.commit()
    data = (await client.get(f"{API}/users/me/export", headers=headers)).json()
    assert data["subscriptions"][0]["plan"] == "premium_monthly" and data["subscriptions"][0]["status"] == "active"
    assert "SECRET" not in json.dumps(data)


async def test_deletion_requires_the_current_password(client):
    _uid, headers, _ = await _register(client)
    wrong = await client.request("DELETE", f"{API}/users/me", json={"password": "not-my-password"}, headers=headers)
    assert wrong.status_code == 400
    assert (await client.get(f"{API}/users/me", headers=headers)).status_code == 200  # still there
    assert (await client.request("DELETE", f"{API}/users/me", json={})).status_code in (401, 422)


async def test_deletion_erases_personal_data_and_keeps_only_what_the_law_requires(client, make_user, session_factory):
    uid, headers, refresh = await _register(client)
    other, other_headers = await make_user("other@example.com")
    await _populate(session_factory, uid, other.id)
    async with session_factory() as db:
        db.add(CommentLike(comment_id=2, user_id=uid))
        await db.commit()

    resp = await client.request("DELETE", f"{API}/users/me", json={"password": PASSWORD}, headers=headers)
    assert resp.status_code == 204

    async with session_factory() as db:
        user = await db.get(User, uid)
        assert user.email == f"deleted-{uid}@deleted.invalid"
        assert user.display_name is None and user.bio is None
        assert user.is_active is False and user.deleted_at is not None
        assert "$2b$" in user.hashed_password  # an unusable random hash, not the old one
        for model in (FavouriteTeam, Device, Reaction, CommentLike, RefreshToken, PollVote):
            assert await db.scalar(select(func.count()).select_from(model).where(model.user_id == uid)) == 0, model.__name__
        mine = (await db.scalars(select(Comment).where(Comment.user_id == uid))).all()
        assert [(c.body, c.status) for c in mine] == [("[deleted]", CommentStatus.DELETED)]
        # other people's data is untouched
        theirs = await db.scalar(select(Comment).where(Comment.user_id == other.id))
        assert theirs.body == "someone else's comment" and theirs.status == CommentStatus.VISIBLE
        entry = await db.scalar(select(AuditLog).where(AuditLog.action == "account.delete"))
        assert entry.target_id == str(uid) and entry.actor_id == uid


async def test_a_deleted_account_cannot_sign_in_refresh_or_use_an_old_token(client):
    uid, headers, refresh = await _register(client)
    assert (await client.request("DELETE", f"{API}/users/me", json={"password": PASSWORD}, headers=headers)).status_code == 204
    assert (await client.get(f"{API}/users/me", headers=headers)).status_code == 401
    assert (await client.post(f"{API}/auth/refresh", json={"refresh_token": refresh}, headers={"X-Client": "mobile"})).status_code == 401
    assert (await client.post(f"{API}/auth/login", json={"email": "leaver@example.com", "password": PASSWORD})).status_code == 401


async def test_the_email_can_be_registered_again_after_deletion(client):
    _uid, headers, _ = await _register(client)
    await client.request("DELETE", f"{API}/users/me", json={"password": PASSWORD}, headers=headers)
    again = await client.post(f"{API}/auth/register", json={"email": "leaver@example.com", "password": PASSWORD, "password_confirm": PASSWORD})
    assert again.status_code == 201


async def test_deletion_clears_the_browser_cookies(client):
    await _register(client)
    resp = await client.request("DELETE", f"{API}/users/me", json={"password": PASSWORD})
    # the register response set cookies on the client jar, so this call is authenticated by cookie
    assert resp.status_code == 204
    cleared = " ".join(resp.headers.get_list("set-cookie")).lower()
    assert "access_token=" in cleared and "refresh_token=" in cleared and ("max-age=0" in cleared or "expires=" in cleared)


@pytest.mark.parametrize("role", [UserRole.AUTHOR, UserRole.EDITOR, UserRole.ADMIN])
async def test_staff_accounts_cannot_erase_themselves(client, make_user, role):
    _u, headers = await make_user(f"{role.value}@example.com", role)
    resp = await client.request("DELETE", f"{API}/users/me", json={"password": PASSWORD}, headers=headers)
    assert resp.status_code == 403
    assert (await client.get(f"{API}/users/me", headers=headers)).status_code == 200


async def test_deletion_cancels_the_subscription_but_retains_the_billing_record(client, make_user, session_factory, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.models.billing import SubscriptionPlan
    from app.models.enums import SubscriptionStatus
    from app.services.billing import providers

    cancelled: list[str] = []

    async def record_cancel(self, subscription_id):
        cancelled.append(subscription_id)

    monkeypatch.setattr(providers.TestBillingProvider, "cancel_subscription", record_cancel)
    user, headers = await make_user("subscriber@example.com")
    async with session_factory() as db:
        plan = SubscriptionPlan(code="premium_monthly", name="Premium", interval="month", price_minor=499, currency="GBP", entitlements=["extended_history"])
        db.add(plan)
        await db.flush()
        db.add(Subscription(user_id=user.id, plan_id=plan.id, status=SubscriptionStatus.ACTIVE, provider="test", provider_subscription_id="sub_77", provider_customer_id="cus_77", current_period_end=datetime.now(timezone.utc) + timedelta(days=10)))
        await db.commit()

    assert (await client.request("DELETE", f"{API}/users/me", json={"password": PASSWORD}, headers=headers)).status_code == 204
    assert cancelled == ["sub_77"]  # the processor was told to stop billing
    async with session_factory() as db:
        sub = await db.scalar(select(Subscription))
        assert sub is not None and sub.status == SubscriptionStatus.CANCELLED and sub.user_id == user.id  # retained for accounting


async def test_deletion_is_refused_if_the_processor_cannot_cancel_the_subscription(client, make_user, session_factory, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.models.billing import SubscriptionPlan
    from app.models.enums import SubscriptionStatus
    from app.services.billing import providers

    async def fail(self, subscription_id):
        raise providers.ProviderError("processor down")

    monkeypatch.setattr(providers.TestBillingProvider, "cancel_subscription", fail)
    user, headers = await make_user("stuck@example.com")
    async with session_factory() as db:
        plan = SubscriptionPlan(code="premium_monthly", name="Premium", interval="month", price_minor=499, currency="GBP", entitlements=["extended_history"])
        db.add(plan)
        await db.flush()
        db.add(Subscription(user_id=user.id, plan_id=plan.id, status=SubscriptionStatus.ACTIVE, provider="test", provider_subscription_id="sub_88", current_period_end=datetime.now(timezone.utc) + timedelta(days=10)))
        await db.commit()

    resp = await client.request("DELETE", f"{API}/users/me", json={"password": PASSWORD}, headers=headers)
    assert resp.status_code == 502
    assert (await client.get(f"{API}/users/me", headers=headers)).status_code == 200  # nothing was erased; try again later
    async with session_factory() as db:
        assert (await db.get(User, user.id)).deleted_at is None


async def test_deletion_is_rate_limited(client, make_user):
    _u, headers = await make_user("hammer@example.com")
    codes = [(await client.request("DELETE", f"{API}/users/me", json={"password": "wrong-password"}, headers=headers)).status_code for _ in range(7)]
    assert codes[:5] == [400] * 5 and codes[5:] == [429, 429]
