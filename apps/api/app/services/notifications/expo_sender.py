"""Expo push delivery (Phase 3 §17). Uses Expo's own push service, which
works from this environment without separate FCM/APNs credentials -- the
Expo project only needs to be linked to an EAS project (a one-time,
external `expo.dev` account step, not something this code can do) for
`getExpoPushTokenAsync` to return a real token client-side; server-side
delivery here has no such dependency once a token exists.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.models.device import Device
from app.services.notifications.base import DeliveryResult, NotificationPayload, PushSender

logger = logging.getLogger(__name__)

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_MAX_ATTEMPTS = 3


class ExpoPushSender(PushSender):
    async def send(self, device: Device, payload: NotificationPayload) -> DeliveryResult:
        if not device.expo_push_token:
            return DeliveryResult(success=False)

        body = {
            "to": device.expo_push_token,
            "title": payload.title,
            "body": payload.body,
            "data": payload.data,
        }

        result = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(_EXPO_PUSH_URL, json=body)
                    resp.raise_for_status()
                    result = resp.json()
                break
            except httpx.HTTPError as exc:
                logger.warning(
                    "Expo push request failed for device=%s (attempt %d): %s", device.id, attempt, exc
                )
                if attempt >= _MAX_ATTEMPTS:
                    return DeliveryResult(success=False)
                await asyncio.sleep(1.0 * (2 ** (attempt - 1)))

        ticket = (result or {}).get("data") or {}
        if isinstance(ticket, list):
            ticket = ticket[0] if ticket else {}
        if ticket.get("status") == "error":
            error_type = (ticket.get("details") or {}).get("error")
            logger.warning("Expo push error for device=%s: %s", device.id, ticket.get("message"))
            return DeliveryResult(success=False, should_remove_device=error_type == "DeviceNotRegistered")

        return DeliveryResult(success=True)
