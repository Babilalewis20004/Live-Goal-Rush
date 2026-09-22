"""Web Push delivery (Phase 3 §18), via VAPID -- no external account
needed (unlike Expo/EAS), the keypair is generated locally (see
`apps/api/.env.example`).
"""

from __future__ import annotations

import asyncio
import json
import logging

from pywebpush import WebPushException, webpush

from app.core.config import settings
from app.models.device import Device
from app.services.notifications.base import DeliveryResult, NotificationPayload, PushSender

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3


class WebPushSender(PushSender):
    async def send(self, device: Device, payload: NotificationPayload) -> DeliveryResult:
        if not (device.web_push_endpoint and device.web_push_p256dh and device.web_push_auth):
            return DeliveryResult(success=False)
        if not settings.vapid_private_key:
            logger.warning("Web push skipped for device=%s: no VAPID key configured", device.id)
            return DeliveryResult(success=False)

        data = json.dumps({"title": payload.title, "body": payload.body, "data": payload.data})

        def _sync_send() -> None:
            webpush(
                subscription_info={
                    "endpoint": device.web_push_endpoint,
                    "keys": {"p256dh": device.web_push_p256dh, "auth": device.web_push_auth},
                },
                data=data,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
            )

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                await asyncio.to_thread(_sync_send)
                return DeliveryResult(success=True)
            except WebPushException as exc:
                status_code = getattr(exc.response, "status_code", None)
                if status_code in (404, 410):
                    logger.info(
                        "Web push subscription gone for device=%s (status=%s)", device.id, status_code
                    )
                    return DeliveryResult(success=False, should_remove_device=True)
                logger.warning("Web push error for device=%s (attempt %d): %s", device.id, attempt, exc)
                if attempt >= _MAX_ATTEMPTS:
                    return DeliveryResult(success=False)
                await asyncio.sleep(1.0 * (2 ** (attempt - 1)))

        return DeliveryResult(success=False)
