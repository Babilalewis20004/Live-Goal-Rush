"""Provider-independent push delivery abstraction (Phase 3 §19), mirroring
`services/providers/base.py`'s style: the rest of the app depends only on
`PushSender`, never on Expo/Web Push specifics directly.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.models.device import Device


@dataclass(frozen=True)
class NotificationPayload:
    title: str
    body: str
    # {"type": "match"|"team"|"competition", "id": ...} -- the deep-link
    # contract both the mobile tap handler and the web service worker's
    # notificationclick handler read (Phase 3 §17/§18).
    data: dict[str, Any]


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    # True when the provider reported the token/subscription itself is
    # gone (not a transient failure) -- the caller should delete the
    # `Device` row rather than keep retrying it forever.
    should_remove_device: bool = False


class PushSender(ABC):
    @abstractmethod
    async def send(self, device: Device, payload: NotificationPayload) -> DeliveryResult: ...

    async def send_many(self, devices: list[Device], payload: NotificationPayload, *, concurrency: int = 20) -> list[DeliveryResult]:
        """Deliver one payload to many devices; results are in the order of `devices`. The default sends each
        device independently with bounded concurrency; a sender whose provider accepts batches overrides this."""
        gate = asyncio.Semaphore(concurrency)

        async def one(device: Device) -> DeliveryResult:
            async with gate:
                try:
                    return await self.send(device, payload)
                except Exception:  # one bad device must not abort the fan-out
                    return DeliveryResult(success=False)

        return list(await asyncio.gather(*(one(d) for d in devices)))
