"""Administrative audit trail (Phase 7).

`record` adds the entry to the caller's session and does NOT commit: the audit row and the action it describes
commit (or roll back) together, so there is never an action without a record or a record of something that did
not happen. Entries are append-only; nothing in the application updates or deletes them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import AuditLog
from app.models.user import User

# Keys that must never be stored in `details`, however a caller names them.
_FORBIDDEN_DETAIL_KEYS = ("password", "token", "secret", "email", "authorization")


def _actor_label(actor: User | None, label: str | None) -> str:
    if label:
        return label[:64]
    if actor is None:
        return "system"
    return f"user:{actor.id} ({actor.role.value})"[:64]


def record(
    db: AsyncSession,
    *,
    action: str,
    target_type: str,
    target_id: int | str,
    actor: User | None = None,
    actor_label: str | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    clean = {k: v for k, v in (details or {}).items() if not any(bad in k.lower() for bad in _FORBIDDEN_DETAIL_KEYS)}
    entry = AuditLog(
        actor_id=actor.id if actor is not None else None,
        actor_label=_actor_label(actor, actor_label),
        action=action[:64],
        target_type=target_type[:32],
        target_id=str(target_id)[:64],
        reason=reason.strip()[:300] if reason else None,
        ip_address=ip_address[:64] if ip_address else None,
        details=clean or None,
    )
    db.add(entry)
    return entry


async def list_entries(
    db: AsyncSession,
    *,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    actor_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditLog], int]:
    from sqlalchemy import func

    clauses = []
    if action:
        clauses.append(AuditLog.action == action)
    if target_type:
        clauses.append(AuditLog.target_type == target_type)
    if target_id:
        clauses.append(AuditLog.target_id == target_id)
    if actor_id is not None:
        clauses.append(AuditLog.actor_id == actor_id)
    total = await db.scalar(select(func.count()).select_from(AuditLog).where(*clauses)) or 0
    rows = (
        await db.scalars(
            select(AuditLog).where(*clauses).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(page_size).offset((page - 1) * page_size)
        )
    ).all()
    return list(rows), total
