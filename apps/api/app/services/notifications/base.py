"""Provider-independent push delivery abstraction (Phase 3 §19), mirroring
`services/providers/base.py`'s style: the rest of the app depends only on
`PushSender`, never on Expo/Web Push specifics directly.
"""

from __future__ import annotations

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
