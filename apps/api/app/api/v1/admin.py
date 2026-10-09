"""Administrator API (Phase 7): inspect users and subscriptions, read the audit trail, triage failed
background jobs, and see system health at a glance.

Deliberately small. Content, comments and reports are already managed by the editor and moderation
endpoints; this adds only what an operator could previously do only with database access. Everything
here requires the ADMIN role (`AdminDep`) -- checked on the server on every request -- and anything that
changes state writes an audit entry in the same transaction.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.api.deps import AdminDep, DbDep, PaginationDep, RedisServiceDep
from app.core.config import settings
from app.core.redis_keys import RedisKeys  # noqa: F401  (kept for parity with sibling routers)
from app.db.session import engine
from app.models.billing import PaymentEvent, Subscription, SubscriptionPlan
from app.models.community import Comment, CommentReport, ProfileReport
from app.models.enums import MatchStatus, PaymentEventStatus, ReportStatus
from app.models.match import Match
from app.models.operations import FailedJob
from app.models.user import User
from app.schemas.admin import (
    AdminSubscriptionOut,
    AdminUserDetail,
    AdminUserOut,
    AuditEntryOut,
    FailedJobOut,
    ResolveRequest,
    SystemStatusOut,
)
from app.schemas.common import Page
from app.services import audit_service as audit
from app.services.billing.entitlements import entitlements_for
from app.websocket.manager import manager

router = APIRouter()


def _escape_like(text_: str) -> str:
    return text_.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _latest_subscription(db, user_ids: list[int]) -> dict[int, tuple[str, str]]:
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(Subscription.user_id, Subscription.status, SubscriptionPlan.code, Subscription.created_at)
            .join(SubscriptionPlan, SubscriptionPlan.id == Subscription.plan_id)
            .where(Subscription.user_id.in_(user_ids))
            .order_by(Subscription.created_at.asc())
        )
    ).all()
    return {uid: (st.value, code) for uid, st, code, _ in rows}  # later rows (newer) overwrite earlier


def _user_out(user: User, sub: tuple[str, str] | None) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role.value,
        is_active=user.is_active,
        suspended_at=user.suspended_at,
        suspended_reason=user.suspended_reason,
        deleted_at=user.deleted_at,
        created_at=user.created_at,
        subscription_status=sub[0] if sub else None,
        subscription_plan=sub[1] if sub else None,
    )


@router.get("/users", response_model=Page[AdminUserOut])
async def list_users(
    admin: AdminDep,
    db: DbDep,
    pagination: PaginationDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    role: str | None = None,
    suspended: bool | None = None,
) -> Page[AdminUserOut]:
    page, page_size = pagination
    clauses = []
    if q:
        pattern = f"%{_escape_like(q.strip().lower())}%"
        clauses.append(or_(func.lower(User.email).like(pattern, escape="\\"), func.lower(func.coalesce(User.display_name, "")).like(pattern, escape="\\")))
    if role:
        clauses.append(User.role == role)
    if suspended is not None:
        clauses.append(User.suspended_at.is_not(None) if suspended else User.suspended_at.is_(None))
    total = await db.scalar(select(func.count()).select_from(User).where(*clauses)) or 0
    users = (await db.scalars(select(User).where(*clauses).order_by(User.id.desc()).limit(page_size).offset((page - 1) * page_size))).all()
    subs = await _latest_subscription(db, [u.id for u in users])
    return Page(items=[_user_out(u, subs.get(u.id)) for u in users], total=total, page=page, page_size=page_size)


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def get_user(user_id: int, admin: AdminDep, db: DbDep) -> AdminUserDetail:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    sub_rows = (
        await db.execute(
            select(Subscription, SubscriptionPlan.code)
            .join(SubscriptionPlan, SubscriptionPlan.id == Subscription.plan_id)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
        )
    ).all()
    entitlements = await entitlements_for(db, user)  # effective set: plan entitlements plus operator grants
    open_reports = (
        (await db.scalar(select(func.count()).select_from(ProfileReport).where(ProfileReport.profile_user_id == user_id, ProfileReport.status == ReportStatus.OPEN)) or 0)
        + (
            await db.scalar(
                select(func.count())
                .select_from(CommentReport)
                .join(Comment, Comment.id == CommentReport.comment_id)
                .where(Comment.user_id == user_id, CommentReport.status == ReportStatus.OPEN)
            )
            or 0
        )
    )
    latest = (sub_rows[0][0].status.value, sub_rows[0][1]) if sub_rows else None
    base = _user_out(user, latest)
    return AdminUserDetail(
        **base.model_dump(),
        subscriptions=[
            AdminSubscriptionOut(
                plan=code, status=s.status.value, provider=s.provider, current_period_end=s.current_period_end,
                cancel_at_period_end=s.cancel_at_period_end, created_at=s.created_at,
            )
            for s, code in sub_rows
        ],
        entitlements=sorted(entitlements),
        open_reports_against=open_reports,
    )


@router.get("/audit-log", response_model=Page[AuditEntryOut])
async def audit_log(
    admin: AdminDep,
    db: DbDep,
    pagination: PaginationDep,
    action: Annotated[str | None, Query(max_length=64)] = None,
    target_type: Annotated[str | None, Query(max_length=32)] = None,
    target_id: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: int | None = None,
) -> Page[AuditEntryOut]:
    page, page_size = pagination
    entries, total = await audit.list_entries(
        db, action=action, target_type=target_type, target_id=target_id, actor_id=actor_id, page=page, page_size=page_size
    )
    return Page(items=[AuditEntryOut.model_validate(e) for e in entries], total=total, page=page, page_size=page_size)


@router.get("/failed-jobs", response_model=Page[FailedJobOut])
async def failed_jobs(
    admin: AdminDep,
    db: DbDep,
    pagination: PaginationDep,
    resolved: bool = False,
    task: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[FailedJobOut]:
    page, page_size = pagination
    clauses = [FailedJob.resolved_at.is_not(None) if resolved else FailedJob.resolved_at.is_(None)]
    if task:
        clauses.append(FailedJob.task_name == task)
    total = await db.scalar(select(func.count()).select_from(FailedJob).where(*clauses)) or 0
    rows = (await db.scalars(select(FailedJob).where(*clauses).order_by(FailedJob.failed_at.desc()).limit(page_size).offset((page - 1) * page_size))).all()
    return Page(items=[FailedJobOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.post("/failed-jobs/{job_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_failed_job(job_id: int, payload: ResolveRequest, admin: AdminDep, db: DbDep) -> None:
    job = await db.get(FailedJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Failed job not found")
    if job.resolved_at is None:
        job.resolved_at, job.resolved_by = datetime.now(timezone.utc), admin.id
        audit.record(db, action="failed_job.resolve", target_type="failed_job", target_id=job.id, actor=admin, reason=payload.note, details={"task": job.task_name})
    await db.commit()


@router.get("/system", response_model=SystemStatusOut)
async def system_status(admin: AdminDep, db: DbDep, redis: RedisServiceDep) -> SystemStatusOut:
    """One screen of answers to 'is anything wrong?': dependencies, queue depth, job failures, data freshness."""
    from app.main import _provider_configured, _redis_healthy  # local import: main imports this router

    database_ok = True
    try:
        await asyncio.wait_for(db.execute(select(1)), timeout=2)
    except Exception:
        database_ok = False
    redis_ok = await _redis_healthy(redis)

    queue_length: int | None = None
    provider: dict = {"configured": _provider_configured()}
    if redis_ok:
        try:
            queue_length = int(await redis.raw.llen("football"))
            from app.services.metrics_aggregation import read_aggregate_async

            counters, _gauges = await read_aggregate_async(redis.raw)
            totals: dict[str, int] = {}
            for role_counters in counters.values():
                for name, value in role_counters.items():
                    totals[name] = totals.get(name, 0) + int(value)
            provider.update(
                requests=totals.get("provider_requests_total", 0),
                errors=totals.get("provider_errors_total", 0),
                rate_limited=totals.get("provider_rate_limited_total", 0),
            )
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    unresolved = await db.scalar(select(func.count()).select_from(FailedJob).where(FailedJob.resolved_at.is_(None))) or 0
    newest_sync = await db.scalar(select(func.max(Match.last_synced_at)))
    live_unsynced = await db.scalar(
        select(func.count()).select_from(Match).where(Match.status.in_([MatchStatus.LIVE, MatchStatus.HALFTIME]), or_(Match.last_synced_at.is_(None), Match.last_synced_at < now - timedelta(minutes=5)))
    ) or 0
    open_comment_reports = await db.scalar(select(func.count()).select_from(CommentReport).where(CommentReport.status == ReportStatus.OPEN)) or 0
    open_profile_reports = await db.scalar(select(func.count()).select_from(ProfileReport).where(ProfileReport.status == ReportStatus.OPEN)) or 0
    failed_payments = await db.scalar(
        select(func.count()).select_from(PaymentEvent).where(PaymentEvent.status == PaymentEventStatus.FAILED, PaymentEvent.received_at > now - timedelta(days=1))
    ) or 0
    pool = engine.pool
    return SystemStatusOut(
        version=settings.app_version,
        environment=settings.environment,
        database="ok" if database_ok else "unavailable",
        redis="ok" if redis_ok else "unavailable",
        provider=provider,
        queue_length=queue_length,
        unresolved_failed_jobs=unresolved,
        websocket_connections=manager.connection_count(),
        db_pool={
            "size": pool.size() if hasattr(pool, "size") else 0,
            "checked_out": pool.checkedout() if hasattr(pool, "checkedout") else 0,
            "overflow": pool.overflow() if hasattr(pool, "overflow") else 0,
        },
        data_freshness={
            "newest_match_sync": newest_sync.isoformat() if newest_sync else None,
            "live_matches_not_synced_for_5_minutes": live_unsynced,
        },
        unresolved_reports={"comments": open_comment_reports, "profiles": open_profile_reports},
        recent_payment_event_failures=failed_payments,
    )
