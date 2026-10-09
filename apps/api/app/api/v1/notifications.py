from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, DevicesServiceDep, NotificationPreferencesServiceDep
from app.db.session import get_db
from app.core.config import settings
from app.events.schemas import RealtimeEventType
from app.models.enums import DevicePlatform, NotificationScope
from app.schemas.discovery import ContentPreferenceIn, ContentPreferenceOut
from app.services import content_notification_service as content_prefs
from app.schemas.notification import (
    DeviceOut,
    DeviceRegister,
    NotificationPreferenceIn,
    NotificationPreferenceOut,
    WebPushSubscribe,
)

router = APIRouter()


@router.get("/vapid-public-key")
async def get_vapid_public_key() -> dict[str, str | None]:
    """`None` (rather than an error) when no keypair is configured -- the
    web client treats that as "push unavailable here" and simply doesn't
    offer the subscribe UI, matching the rest of this app's fail-soft
    stance on optional infra (spec §18)."""
    return {"public_key": settings.vapid_public_key or None}


@router.post("/web-push/subscribe", response_model=DeviceOut, status_code=201)
async def subscribe_web_push(
    payload: WebPushSubscribe, current_user: CurrentUserDep, service: DevicesServiceDep
) -> DeviceOut:
    device = await service.register(
        current_user.id,
        DeviceRegister(
            platform=DevicePlatform.WEB,
            web_push_endpoint=payload.endpoint,
            web_push_p256dh=payload.keys.p256dh,
            web_push_auth=payload.keys.auth,
        ),
    )
    return DeviceOut.model_validate(device)


@router.get("/preferences", response_model=list[NotificationPreferenceOut])
async def list_preferences(
    current_user: CurrentUserDep, service: NotificationPreferencesServiceDep
) -> list[NotificationPreferenceOut]:
    prefs = await service.list_for_user(current_user.id)
    return [NotificationPreferenceOut.model_validate(p) for p in prefs]


@router.patch("/preferences", response_model=NotificationPreferenceOut)
async def update_preference(
    payload: NotificationPreferenceIn,
    current_user: CurrentUserDep,
    service: NotificationPreferencesServiceDep,
) -> NotificationPreferenceOut:
    pref = await service.upsert(current_user.id, payload)
    return NotificationPreferenceOut.model_validate(pref)


@router.delete("/preferences", status_code=204)
async def reset_preference(
    current_user: CurrentUserDep,
    service: NotificationPreferencesServiceDep,
    scope_type: NotificationScope,
    event_type: RealtimeEventType,
    scope_id: int | None = Query(default=None),
) -> Response:
    """Remove one override, restoring the default for that scope + event
    (Phase 5: the "Default" choice of the per-favourite settings). Same
    scope rules as PATCH; 204 whether or not an override existed."""
    if (scope_type == NotificationScope.GLOBAL) != (scope_id is None):
        raise HTTPException(
            status_code=422,
            detail="scope_id is required for team/competition/match scopes and must be omitted for global",
        )
    await service.remove(current_user.id, scope_type, scope_id, event_type)
    return Response(status_code=204)


@router.get("/content-preferences", response_model=list[ContentPreferenceOut])
async def get_content_preferences(
    current_user: CurrentUserDep, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[ContentPreferenceOut]:
    """Which kinds of article notification the caller has switched on. All
    default to off -- nothing is sent until the user opts in."""
    return await content_prefs.list_preferences(db, current_user.id)


@router.put("/content-preferences", response_model=ContentPreferenceOut)
async def set_content_preference(
    payload: ContentPreferenceIn, current_user: CurrentUserDep, db: Annotated[AsyncSession, Depends(get_db)]
) -> ContentPreferenceOut:
    return await content_prefs.set_preference(db, current_user.id, payload.kind, payload.enabled)
