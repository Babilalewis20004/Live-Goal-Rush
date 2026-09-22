"""NotificationService delivery tests (Phase 3 §31): fan-out across a
user's multiple devices, and stale-device cleanup on a permanent delivery
failure. Uses fake `PushSender`s (no real Expo/Web Push network calls) --
`ExpoPushSender`/`WebPushSender` themselves are thin HTTP wrappers around
third-party services and are not worth hitting in a test suite.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.events.schemas import RealtimeEventType
from app.models.device import Device
from app.models.enums import DevicePlatform
from app.models.user import User
from app.services.football_service import FootballService
from app.services.notification_dispatch_service import NotificationTarget
from app.services.notifications.base import DeliveryResult, NotificationPayload, PushSender
from app.services.notifications.service import NotificationService
from app.services.providers.mock_provider import MockFootballDataProvider
from app.services.providers.schemas import ProviderCompetition, ProviderMatch, ProviderTeam

_COMPETITION = ProviderCompetition(provider_id="comp-y", name="Test League", country="Testland", type="league")
_HOME = ProviderTeam(provider_id="team-home-y", name="Home FC", short_name="HOM", country="Testland")
_AWAY = ProviderTeam(provider_id="team-away-y", name="Away FC", short_name="AWY", country="Testland")


class _FakeSender(PushSender):
    def __init__(self, result: DeliveryResult) -> None:
        self.result = result
        self.calls: list[Device] = []

    async def send(self, device: Device, payload: NotificationPayload) -> DeliveryResult:
        self.calls.append(device)
        return self.result


async def _seed_match(session):
    service = FootballService(db=session, provider=MockFootballDataProvider())
    match = await service.sync_match(
        ProviderMatch(
            provider_id="match-y",
            competition=_COMPETITION,
            home_team=_HOME,
            away_team=_AWAY,
            kickoff_time=datetime(2026, 9, 21, 19, 0, tzinfo=timezone.utc),
            status="live",
            home_score=2,
            away_score=1,
            minute=70,
            events=[],
        )
    )
    await session.commit()
    return match


async def test_delivers_to_every_registered_device(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        match = await _seed_match(session)
        user = User(email="multi-device@example.com", hashed_password="x")
        session.add(user)
        await session.flush()
        session.add(Device(user_id=user.id, platform=DevicePlatform.EXPO_IOS, expo_push_token="tok-ios"))
        session.add(Device(user_id=user.id, platform=DevicePlatform.EXPO_ANDROID, expo_push_token="tok-android"))
        await session.commit()

        fake = _FakeSender(DeliveryResult(success=True))
        service = NotificationService(session)
        service._senders = {DevicePlatform.EXPO_IOS: fake, DevicePlatform.EXPO_ANDROID: fake}

        target = NotificationTarget(
            user_id=user.id, match_id=match.id, event_type=RealtimeEventType.GOAL, dedup_key="event:1"
        )
        await service.send_to_user(target)

    assert len(fake.calls) == 2
    assert {d.expo_push_token for d in fake.calls} == {"tok-ios", "tok-android"}


async def test_permanent_failure_removes_stale_device(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        match = await _seed_match(session)
        user = User(email="stale-device@example.com", hashed_password="x")
        session.add(user)
        await session.flush()
        device = Device(user_id=user.id, platform=DevicePlatform.EXPO_IOS, expo_push_token="tok-gone")
        session.add(device)
        await session.commit()
        device_id = device.id

        fake = _FakeSender(DeliveryResult(success=False, should_remove_device=True))
        service = NotificationService(session)
        service._senders = {DevicePlatform.EXPO_IOS: fake}

        target = NotificationTarget(
            user_id=user.id, match_id=match.id, event_type=RealtimeEventType.GOAL, dedup_key="event:2"
        )
        await service.send_to_user(target)

        remaining = await session.execute(select(Device).where(Device.id == device_id))

    assert remaining.scalars().all() == []


async def test_transient_failure_keeps_device_registered(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        match = await _seed_match(session)
        user = User(email="transient-fail@example.com", hashed_password="x")
        session.add(user)
        await session.flush()
        device = Device(user_id=user.id, platform=DevicePlatform.EXPO_IOS, expo_push_token="tok-flaky")
        session.add(device)
        await session.commit()
        device_id = device.id

        fake = _FakeSender(DeliveryResult(success=False, should_remove_device=False))
        service = NotificationService(session)
        service._senders = {DevicePlatform.EXPO_IOS: fake}

        target = NotificationTarget(
            user_id=user.id, match_id=match.id, event_type=RealtimeEventType.GOAL, dedup_key="event:3"
        )
        await service.send_to_user(target)

        remaining = await session.execute(select(Device).where(Device.id == device_id))

    assert len(remaining.scalars().all()) == 1


async def test_no_devices_is_a_noop(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        match = await _seed_match(session)
        user = User(email="no-devices@example.com", hashed_password="x")
        session.add(user)
        await session.flush()
        await session.commit()

        service = NotificationService(session)
        target = NotificationTarget(
            user_id=user.id, match_id=match.id, event_type=RealtimeEventType.GOAL, dedup_key="event:4"
        )
        # Must not raise even though no senders were ever exercised.
        await service.send_to_user(target)
