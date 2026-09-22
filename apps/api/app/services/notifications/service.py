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

        devices_result = await self._db.execute(select(Device).where(Device.user_id == target.user_id))
        devices = list(devices_result.scalars().all())
        if not devices:
            return

        payload = self._build_payload(target, match)
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
                logger.info("Push delivery failed for user=%s device=%s", target.user_id, device.id)
                if delivery.should_remove_device:
                    stale_device_ids.append(device.id)

        if stale_device_ids:
            await self._db.execute(delete(Device).where(Device.id.in_(stale_device_ids)))
            await self._db.commit()

    @staticmethod
    def _build_payload(target: NotificationTarget, match: Match) -> NotificationPayload:
        title = _EVENT_TITLES.get(target.event_type, "Match update")
        body = f"{match.home_team.name} {match.home_score}-{match.away_score} {match.away_team.name}"
        return NotificationPayload(title=title, body=body, data={"type": "match", "id": match.id})
