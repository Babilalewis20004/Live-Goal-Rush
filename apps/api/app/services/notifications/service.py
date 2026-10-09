"""Provider-agnostic notification delivery entry point (Phase 3 §19/§20).

`worker/notification_tasks.py` is the only caller -- it already has a
deduplicated, preference-matched `NotificationTarget` list from
`notification_dispatch_service.resolve_targets`; this layer's only job is
turning each target into an actual push, fanned out across every device
that user has registered, and cleaning up devices the provider reports as
gone.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.events.schemas import RealtimeEventType
from app.models.device import Device
from app.models.enums import DevicePlatform
from app.models.match import Match
from app.services.metrics import metrics
from app.services.notification_dispatch_service import NotificationTarget
from app.services.notifications.base import NotificationPayload, PushSender
from app.services.notifications.expo_sender import ExpoPushSender
from app.services.notifications.web_sender import WebPushSender

logger = logging.getLogger(__name__)

_DEVICE_QUERY_CHUNK = 5000

_EVENT_TITLES: dict[RealtimeEventType, str] = {
    RealtimeEventType.MATCH_STARTED: "Kick-off",
    RealtimeEventType.GOAL: "Goal!",
    RealtimeEventType.CARD: "Card shown",
    RealtimeEventType.HALF_TIME: "Half-time",
    RealtimeEventType.MATCH_FINISHED: "Full-time",
}


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._senders: dict[DevicePlatform, PushSender] = {
            DevicePlatform.EXPO_IOS: ExpoPushSender(),
            DevicePlatform.EXPO_ANDROID: ExpoPushSender(),
            DevicePlatform.WEB: WebPushSender(),
        }

    async def send_to_user(self, target: NotificationTarget) -> None:
        match = await self._db.scalar(
            select(Match)
            .options(selectinload(Match.home_team), selectinload(Match.away_team))
            .where(Match.id == target.match_id)
        )
        if match is None:
            return

        payload = self._build_payload(target, match)
        await self.send_payload_to_user(target.user_id, payload)

    async def send_to_users(self, targets: list[NotificationTarget]) -> int:
        """Deliver a whole dispatch at once. `send_to_user` in a loop issued four SQL statements per recipient (the
        match, its two teams, the devices): 36,000 statements and over two minutes for a team with 9,000
        followers, before a single push was sent. Here the match is loaded once, devices come in a few set-based
        queries, and pushes go out in provider batches. Returns the number of pushes accepted."""
        by_event: dict[tuple[int, RealtimeEventType], list[NotificationTarget]] = defaultdict(list)
        for target in targets:
            by_event[(target.match_id, target.event_type)].append(target)

        delivered = 0
        for (match_id, _event_type), group in by_event.items():
            match = await self._db.scalar(
                select(Match).options(selectinload(Match.home_team), selectinload(Match.away_team)).where(Match.id == match_id)
            )
            if match is None:
                continue
            payload = self._build_payload(group[0], match)
            delivered += await self._deliver_to_users([t.user_id for t in group], payload)
        return delivered

    async def _deliver_to_users(self, user_ids: list[int], payload: NotificationPayload) -> int:
        devices: list[Device] = []
        for start in range(0, len(user_ids), _DEVICE_QUERY_CHUNK):
            rows = await self._db.execute(select(Device).where(Device.user_id.in_(user_ids[start : start + _DEVICE_QUERY_CHUNK])))
            devices.extend(rows.scalars().all())

        by_sender: dict[int, tuple[PushSender, list[Device]]] = {}
        for device in devices:
            sender = self._senders.get(device.platform)
            if sender is not None:
                by_sender.setdefault(id(sender), (sender, []))[1].append(device)

        stale_device_ids: list[int] = []
        accepted = 0
        for sender, group in by_sender.values():
            for device, delivery in zip(group, await sender.send_many(group, payload)):
                if delivery.success:
                    metrics.notification_sent()
                    accepted += 1
                else:
                    metrics.notification_failed()
                    if delivery.should_remove_device:
                        stale_device_ids.append(device.id)

        for start in range(0, len(stale_device_ids), _DEVICE_QUERY_CHUNK):
            await self._db.execute(delete(Device).where(Device.id.in_(stale_device_ids[start : start + _DEVICE_QUERY_CHUNK])))
        if stale_device_ids:
            await self._db.commit()
        return accepted

    async def send_payload_to_user(self, user_id: int, payload: NotificationPayload) -> None:
        """Fan one payload out to every device the user has registered,
        removing devices the provider reports as gone. Shared by match
        notifications and (discovery) article notifications."""
        devices_result = await self._db.execute(select(Device).where(Device.user_id == user_id))
        devices = list(devices_result.scalars().all())
        if not devices:
            return

        stale_device_ids: list[int] = []
        for device in devices:
            sender = self._senders.get(device.platform)
            if sender is None:
                continue
            delivery = await sender.send(device, payload)
            if delivery.success:
                metrics.notification_sent()
            else:
                metrics.notification_failed()
                logger.info("Push delivery failed for user=%s device=%s", user_id, device.id)
                if delivery.should_remove_device:
                    stale_device_ids.append(device.id)

        if stale_device_ids:
            await self._db.execute(delete(Device).where(Device.id.in_(stale_device_ids)))
            await self._db.commit()

    @staticmethod
    def build_article_payload(slug: str, title: str, excerpt: str) -> NotificationPayload:
        """Same `{type, id}` deep-link contract as match notifications; for
        articles `id` is the slug, so `/article/<slug>` opens the page."""
        body = excerpt if len(excerpt) <= 140 else excerpt[:137].rstrip() + "…"
        return NotificationPayload(title=title, body=body, data={"type": "article", "id": slug})

    @staticmethod
    def _build_payload(target: NotificationTarget, match: Match) -> NotificationPayload:
        title = _EVENT_TITLES.get(target.event_type, "Match update")
        body = f"{match.home_team.name} {match.home_score}-{match.away_score} {match.away_team.name}"
        return NotificationPayload(title=title, body=body, data={"type": "match", "id": match.id})
