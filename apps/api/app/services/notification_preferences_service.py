"""Device registration + notification preference CRUD (Phase 3 §14/§16)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.notification import NotificationPreference
from app.schemas.notification import DeviceRegister, NotificationPreferenceIn


class DevicesService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def register(self, user_id: int, payload: DeviceRegister) -> Device:
        """A push token/subscription belongs to exactly one row globally
        (enforced by the partial unique indexes on `Device`) -- if this
        token is already registered (app reinstall, a token that hasn't
        rotated, or a different user now signed in on the same device),
        this reassigns it rather than erroring."""
        token_column = Device.expo_push_token if payload.expo_push_token else Device.web_push_endpoint
        token_value = payload.expo_push_token or payload.web_push_endpoint

        existing = await self._db.scalar(select(Device).where(token_column == token_value))
        now = datetime.now(timezone.utc)
        if existing is not None:
            existing.user_id = user_id
            existing.platform = payload.platform
            existing.web_push_p256dh = payload.web_push_p256dh
            existing.web_push_auth = payload.web_push_auth
            existing.last_seen_at = now
            await self._db.commit()
            return existing

        device = Device(
            user_id=user_id,
            platform=payload.platform,
            expo_push_token=payload.expo_push_token,
            web_push_endpoint=payload.web_push_endpoint,
            web_push_p256dh=payload.web_push_p256dh,
            web_push_auth=payload.web_push_auth,
            last_seen_at=now,
        )
        self._db.add(device)
        await self._db.commit()
        await self._db.refresh(device)
        return device

    async def list_for_user(self, user_id: int) -> list[Device]:
        result = await self._db.execute(select(Device).where(Device.user_id == user_id))
        return list(result.scalars().all())

    async def remove(self, user_id: int, device_id: int) -> None:
        await self._db.execute(delete(Device).where(Device.user_id == user_id, Device.id == device_id))
        await self._db.commit()


class NotificationPreferencesService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_for_user(self, user_id: int) -> list[NotificationPreference]:
        result = await self._db.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        return list(result.scalars().all())

    async def upsert(self, user_id: int, payload: NotificationPreferenceIn) -> NotificationPreference:
        stmt = (
            pg_insert(NotificationPreference)
            .values(
                user_id=user_id,
                scope_type=payload.scope_type,
                scope_id=payload.scope_id,
                event_type=payload.event_type,
                enabled=payload.enabled,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "scope_type", "scope_id", "event_type"],
                set_={"enabled": payload.enabled},
            )
            .returning(NotificationPreference)
        )
        result = await self._db.execute(stmt)
        await self._db.commit()
        return result.scalar_one()
