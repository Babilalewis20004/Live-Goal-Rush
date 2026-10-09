"""Notification fan-out at scale (Phase 7 §10, §28 scenario 7)."""

import json

import httpx
import pytest
from sqlalchemy import func, select, text

from app.events.schemas import RealtimeEvent, RealtimeEventType
from app.models.device import Device
from app.models.enums import DevicePlatform
from app.models.favourite import FavouriteTeam
from app.models.match import Match
from app.models.notification import NotificationLog
from app.models.team import Team
from app.services.notification_dispatch_service import NotificationTarget, resolve_targets
from app.services.notifications import expo_sender as expo_module
from app.services.notifications.base import DeliveryResult, NotificationPayload, PushSender
from app.services.notifications.expo_sender import ExpoPushSender
from app.services.notifications.service import NotificationService


async def _arsenal_match(session_factory, lookup):
    team_id = await lookup(Team, "Arsenal")
    async with session_factory() as db:
        match = await db.scalar(select(Match).where((Match.home_team_id == team_id) | (Match.away_team_id == team_id)).limit(1))
    return team_id, match


async def test_a_team_with_more_than_eight_thousand_followers_can_be_notified(seeded_client, session_factory, lookup):
    """4 bind parameters per recipient against the driver's 32,767 limit: one INSERT for 8,300 followers raised
    an error and notified nobody -- exactly for the biggest teams."""
    team_id, match = await _arsenal_match(session_factory, lookup)
    async with session_factory() as db:
        await db.execute(
            text(
                "INSERT INTO users (email, hashed_password, is_active, role, profile_public) "
                "SELECT 'fan' || g || '@example.test', 'x', true, 'USER', false FROM generate_series(1, 8300) g"
            )
        )
        await db.execute(
            text("INSERT INTO favourite_teams (user_id, team_id) SELECT id, :team FROM users WHERE email LIKE 'fan%'"),
            {"team": team_id},
        )
        await db.commit()

    event = RealtimeEvent(type=RealtimeEventType.GOAL, match_id=str(match.id), data={"event": {"id": "big-goal"}})
    async with session_factory() as db:
        targets = await resolve_targets(db, event)
    assert len(targets) == 8300
    assert len({t.user_id for t in targets}) == 8300

    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 8300
        again = await resolve_targets(db, event)
    assert again == []  # redelivery of the same goal notifies nobody twice


async def test_a_retry_after_a_partial_claim_never_notifies_anyone_twice(seeded_client, session_factory, lookup, make_user):
    team_id, match = await _arsenal_match(session_factory, lookup)
    users = [(await make_user(f"f{i}@example.com"))[0] for i in range(6)]
    async with session_factory() as db:
        db.add_all([FavouriteTeam(user_id=u.id, team_id=team_id) for u in users])
        # a previous attempt claimed the first three before it died
        db.add_all([NotificationLog(user_id=u.id, match_id=match.id, event_type="GOAL", dedup_key="event:g1") for u in users[:3]])
        await db.commit()
    event = RealtimeEvent(type=RealtimeEventType.GOAL, match_id=str(match.id), data={"event": {"id": "g1"}})
    async with session_factory() as db:
        targets = await resolve_targets(db, event)
    assert sorted(t.user_id for t in targets) == sorted(u.id for u in users[3:])


class Recorder(PushSender):
    def __init__(self, fail_for: set[int] = frozenset(), gone: set[int] = frozenset()):
        self.sent: list[tuple[int, NotificationPayload]] = []
        self.fail_for, self.gone = fail_for, gone

    async def send(self, device, payload):
        self.sent.append((device.id, payload))
        if device.id in self.gone:
            return DeliveryResult(success=False, should_remove_device=True)
        return DeliveryResult(success=device.id not in self.fail_for)


async def _setup_followers(session_factory, lookup, make_user, count=4):
    team_id, match = await _arsenal_match(session_factory, lookup)
    users = [(await make_user(f"g{i}@example.com"))[0] for i in range(count)]
    async with session_factory() as db:
        for i, u in enumerate(users):
            db.add(FavouriteTeam(user_id=u.id, team_id=team_id))
            db.add(Device(user_id=u.id, platform=DevicePlatform.EXPO_IOS, expo_push_token=f"ExponentPushToken[d{i}a]"))
            if i % 2 == 0:
                db.add(Device(user_id=u.id, platform=DevicePlatform.EXPO_ANDROID, expo_push_token=f"ExponentPushToken[d{i}b]"))
        await db.commit()
    return match, users


async def test_batch_delivery_matches_one_by_one_delivery(seeded_client, session_factory, lookup, make_user):
    match, users = await _setup_followers(session_factory, lookup, make_user)
    targets = [NotificationTarget(user_id=u.id, match_id=match.id, event_type=RealtimeEventType.GOAL, dedup_key="k") for u in users]

    async with session_factory() as db:
        single = Recorder()
        service = NotificationService(db)
        service._senders = {p: single for p in DevicePlatform}
        for target in targets:
            await service.send_to_user(target)

    async with session_factory() as db:
        batch = Recorder()
        service = NotificationService(db)
        service._senders = {p: batch for p in DevicePlatform}
        accepted = await service.send_to_users(targets)

    assert sorted(d for d, _ in batch.sent) == sorted(d for d, _ in single.sent)
    assert {(p.title, p.body, json.dumps(p.data, sort_keys=True)) for _, p in batch.sent} == {
        (p.title, p.body, json.dumps(p.data, sort_keys=True)) for _, p in single.sent
    }  # identical title/body/deep link
    assert accepted == len(batch.sent) == 6


async def test_batch_delivery_issues_a_constant_number_of_queries(seeded_client, session_factory, lookup, make_user, test_engine):
    from sqlalchemy import event

    match, users = await _setup_followers(session_factory, lookup, make_user, count=8)
    targets = [NotificationTarget(user_id=u.id, match_id=match.id, event_type=RealtimeEventType.GOAL, dedup_key="k") for u in users]
    statements = []
    listener = lambda conn, cur, stmt, *a: statements.append(stmt)  # noqa: E731
    event.listen(test_engine.sync_engine, "before_cursor_execute", listener)
    try:
        async with session_factory() as db:
            service = NotificationService(db)
            service._senders = {p: Recorder() for p in DevicePlatform}
            await service.send_to_users(targets)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", listener)
    assert len(statements) <= 5, f"{len(statements)} statements for {len(targets)} recipients"


async def test_devices_the_provider_reports_gone_are_removed_in_bulk_and_failures_are_kept(seeded_client, session_factory, lookup, make_user):
    match, users = await _setup_followers(session_factory, lookup, make_user)
    async with session_factory() as db:
        ids = [d.id for d in (await db.scalars(select(Device).order_by(Device.id))).all()]
    targets = [NotificationTarget(user_id=u.id, match_id=match.id, event_type=RealtimeEventType.GOAL, dedup_key="k") for u in users]
    async with session_factory() as db:
        service = NotificationService(db)
        service._senders = {p: Recorder(fail_for={ids[1]}, gone={ids[0], ids[2]}) for p in DevicePlatform}
        accepted = await service.send_to_users(targets)
    async with session_factory() as db:
        remaining = {d.id for d in (await db.scalars(select(Device))).all()}
    assert remaining == set(ids) - {ids[0], ids[2]}  # transient failure keeps the device, "gone" removes it
    assert accepted == len(ids) - 3


async def test_one_exploding_device_does_not_stop_the_rest():
    class Flaky(PushSender):
        async def send(self, device, payload):
            if device.id == 2:
                raise RuntimeError("socket exploded")
            return DeliveryResult(success=True)

    devices = [Device(id=i, user_id=i, platform=DevicePlatform.WEB) for i in (1, 2, 3)]
    results = await Flaky().send_many(devices, NotificationPayload("t", "b", {}))
    assert [r.success for r in results] == [True, False, True]


# -- Expo batching ----------------------------------------------------------------------------------------------------


def _expo_devices(n: int, missing_token: set[int] = frozenset()) -> list[Device]:
    return [
        Device(id=i, user_id=i, platform=DevicePlatform.EXPO_IOS, expo_push_token=None if i in missing_token else f"ExponentPushToken[t{i}]")
        for i in range(1, n + 1)
    ]


@pytest.fixture
def expo_requests(monkeypatch):
    seen: list[list[dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        tickets = []
        for message in body:
            if message["to"].endswith("[t7]"):
                tickets.append({"status": "error", "message": "gone", "details": {"error": "DeviceNotRegistered"}})
            elif message["to"].endswith("[t8]"):
                tickets.append({"status": "error", "message": "rate", "details": {"error": "MessageRateExceeded"}})
            else:
                tickets.append({"status": "ok", "id": "x"})
        return httpx.Response(200, json={"data": tickets})

    real = httpx.AsyncClient
    monkeypatch.setattr(expo_module.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}))
    return seen


async def test_expo_notifications_go_out_in_batches_of_one_hundred(expo_requests):
    results = await ExpoPushSender().send_many(_expo_devices(250), NotificationPayload("Goal!", "A 1-0 B", {"type": "match", "id": 1}))
    assert sorted(len(b) for b in expo_requests) == [50, 100, 100]
    assert len(results) == 250
    assert sum(r.success for r in results) == 248  # t7 gone, t8 rate limited


async def test_expo_results_line_up_with_their_devices_and_classify_errors(expo_requests):
    results = await ExpoPushSender().send_many(_expo_devices(9), NotificationPayload("t", "b", {}))
    by_device = dict(enumerate(results, start=1))
    assert by_device[7] == DeliveryResult(success=False, should_remove_device=True)
    assert by_device[8] == DeliveryResult(success=False, should_remove_device=False)
    assert all(by_device[i].success for i in (1, 2, 3, 4, 5, 6, 9))


async def test_devices_without_a_token_are_skipped_not_sent(expo_requests):
    results = await ExpoPushSender().send_many(_expo_devices(4, missing_token={2}), NotificationPayload("t", "b", {}))
    assert [r.success for r in results] == [True, False, True, True]
    assert sum(len(b) for b in expo_requests) == 3


async def test_an_expo_outage_fails_the_batch_without_raising(monkeypatch):
    monkeypatch.setattr(expo_module.asyncio, "sleep", lambda _s: _noop())
    real = httpx.AsyncClient
    monkeypatch.setattr(
        expo_module.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(503)), **{k: v for k, v in kw.items() if k != "transport"}),
    )
    results = await ExpoPushSender().send_many(_expo_devices(3), NotificationPayload("t", "b", {}))
    assert [r.success for r in results] == [False, False, False]


async def _noop():
    return None
