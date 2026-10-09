"""Operational housekeeping (Phase 7): keeps the dead-letter table and expired credentials from growing without bound."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.operations import FailedJob
from app.models.session import PasswordResetToken, RefreshToken
from app.worker.async_runner import run
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

RESOLVED_FAILED_JOB_DAYS = 30
UNRESOLVED_FAILED_JOB_DAYS = 90
SESSION_GRACE_DAYS = 7
BATCH = 5_000


async def _delete_in_batches(db: AsyncSession, model, *conditions) -> int:
    """Delete matching rows `BATCH` at a time, committing between batches. One unbounded DELETE after a long outage
    would hold locks for as long as it runs and trip the database's statement timeout; batches keep every
    statement short and the job resumable (a retry just continues where it stopped)."""
    total = 0
    while True:
        ids = (await db.scalars(select(model.id).where(*conditions).limit(BATCH))).all()
        if not ids:
            return total
        await db.execute(delete(model).where(model.id.in_(ids)))
        await db.commit()
        total += len(ids)


async def purge_operational_data(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Idempotent: deletes only rows past their retention. The audit log is deliberately NOT purged here --
    its retention is a policy decision (docs/security/data-inventory.md), not a housekeeping default."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=SESSION_GRACE_DAYS)
    return {
        "failed_jobs_resolved": await _delete_in_batches(
            db, FailedJob, FailedJob.resolved_at.is_not(None), FailedJob.resolved_at < now - timedelta(days=RESOLVED_FAILED_JOB_DAYS)
        ),
        "failed_jobs_old": await _delete_in_batches(db, FailedJob, FailedJob.failed_at < now - timedelta(days=UNRESOLVED_FAILED_JOB_DAYS)),
        # Expired or revoked sessions and used/expired reset tokens are dead weight (and personal metadata: IP, user agent).
        "refresh_tokens": await _delete_in_batches(db, RefreshToken, RefreshToken.expires_at < cutoff)
        + await _delete_in_batches(db, RefreshToken, RefreshToken.revoked_at.is_not(None), RefreshToken.revoked_at < cutoff),
        "reset_tokens": await _delete_in_batches(db, PasswordResetToken, PasswordResetToken.expires_at < cutoff),
    }


@celery_app.task(name="app.worker.ops_tasks.purge_operational_data")
def purge_operational_data_task() -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            counts = await purge_operational_data(db)
        logger.info("Operational data purged: %s", counts)

    run(_go())
