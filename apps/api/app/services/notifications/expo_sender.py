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
_BATCH_SIZE = 100  # Expo's documented per-request maximum


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

    async def send_many(self, devices: list[Device], payload: NotificationPayload, *, concurrency: int = 5) -> list[DeliveryResult]:
        """Expo accepts up to 100 messages per request, so a goal for thousands of followers is tens of requests
        on one shared connection pool instead of one new TLS connection per device."""
        results: list[DeliveryResult] = [DeliveryResult(success=False)] * len(devices)
        indexed = [(i, d) for i, d in enumerate(devices) if d.expo_push_token]
        gate = asyncio.Semaphore(concurrency)

        async with httpx.AsyncClient(timeout=15.0) as client:

            async def send_batch(batch: list[tuple[int, Device]]) -> None:
                body = [
                    {"to": d.expo_push_token, "title": payload.title, "body": payload.body, "data": payload.data}
                    for _, d in batch
                ]
                tickets: list = []
                async with gate:
                    for attempt in range(1, _MAX_ATTEMPTS + 1):
                        try:
                            resp = await client.post(_EXPO_PUSH_URL, json=body)
                            resp.raise_for_status()
                            tickets = resp.json().get("data") or []
                            break
                        except (httpx.HTTPError, ValueError) as exc:
                            logger.warning("Expo batch of %d failed (attempt %d): %s", len(batch), attempt, exc)
                            if attempt >= _MAX_ATTEMPTS:
                                return
                            await asyncio.sleep(1.0 * (2 ** (attempt - 1)))
                for (position, device), ticket in zip(batch, tickets):
                    if ticket.get("status") == "error":
                        gone = (ticket.get("details") or {}).get("error") == "DeviceNotRegistered"
                        logger.warning("Expo push error for device=%s: %s", device.id, ticket.get("message"))
                        results[position] = DeliveryResult(success=False, should_remove_device=gone)
                    else:
                        results[position] = DeliveryResult(success=True)

            await asyncio.gather(*(send_batch(indexed[i : i + _BATCH_SIZE]) for i in range(0, len(indexed), _BATCH_SIZE)))
        return results
