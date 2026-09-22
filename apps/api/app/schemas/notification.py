from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.events.schemas import RealtimeEventType
from app.models.enums import DevicePlatform, NotificationScope


class DeviceRegister(BaseModel):
    platform: DevicePlatform
    expo_push_token: str | None = None
    web_push_endpoint: str | None = None
    web_push_p256dh: str | None = None
    web_push_auth: str | None = None

    @model_validator(mode="after")
    def one_token_shape_per_platform(self) -> "DeviceRegister":
        if self.platform == DevicePlatform.WEB:
            if not (self.web_push_endpoint and self.web_push_p256dh and self.web_push_auth):
                raise ValueError("web devices require web_push_endpoint/p256dh/auth")
        elif not self.expo_push_token:
            raise ValueError("expo devices require expo_push_token")
        return self


class WebPushKeys(BaseModel):
    p256dh: str
    auth: str


class WebPushSubscribe(BaseModel):
    """Shape of the browser's native `PushSubscription.toJSON()` output --
    matches what `apps/web/lib/push.ts` posts directly, no reshaping
    needed client-side."""

    endpoint: str
    keys: WebPushKeys


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: DevicePlatform
    last_seen_at: datetime | None
    created_at: datetime


class NotificationPreferenceIn(BaseModel):
    scope_type: NotificationScope
    scope_id: int | None = None
    event_type: RealtimeEventType
    enabled: bool

    @model_validator(mode="after")
    def scope_id_matches_scope_type(self) -> "NotificationPreferenceIn":
        needs_id = self.scope_type != NotificationScope.GLOBAL
        if needs_id and self.scope_id is None:
            raise ValueError(f"scope_id is required for scope_type={self.scope_type.value}")
        if not needs_id and self.scope_id is not None:
            raise ValueError("scope_id must be omitted for scope_type=global")
        return self


class NotificationPreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scope_type: NotificationScope
    scope_id: int | None
    event_type: RealtimeEventType
    enabled: bool
