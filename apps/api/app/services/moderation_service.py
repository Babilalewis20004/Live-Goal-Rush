"""Profile reports and account suspension (Phase 6b).

Comment moderation already lives in `CommentService`. This adds the two missing
pieces, kept deliberately small:

* anyone signed in can report a *public* profile (a private one cannot be
  reported or probed -- it does not exist as far as they can tell); moderators
  resolve or dismiss reports;
* admins (and only admins) can suspend an account, which stops sign-in, token
  refresh and every authenticated request, and revokes existing sessions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import log_event
from app.services import audit_service as audit
from app.models.community import ProfileReport
from app.models.enums import ReportStatus, UserRole
from app.models.session import RefreshToken
from app.models.user import User

logger = logging.getLogger(__name__)


class ModerationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProfileReportOut(BaseModel):
    id: int
    profile_user_id: int
    display_name: str
    reason: str
    status: ReportStatus
    created_at: datetime
    suspended: bool


def is_moderator(user: User) -> bool:
    return user.role in (UserRole.EDITOR, UserRole.ADMIN)


class ModerationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def report_profile(self, reporter: User, profile_user_id: int, reason: str) -> None:
        if reporter.id == profile_user_id:
            raise ModerationError("You can't report your own profile.", 400)
        target = await self.db.get(User, profile_user_id)
        if target is None or not target.is_active or not target.profile_public:
            raise ModerationError("Profile not found", 404)  # same answer as "private"
        stmt = (
            pg_insert(ProfileReport)
            .values(profile_user_id=profile_user_id, reporter_id=reporter.id, reason=reason.strip()[:200])
            .on_conflict_do_nothing(constraint="uq_profile_reports_profile_reporter")
        )
        await self.db.execute(stmt)  # a second report from the same person is a harmless no-op
        await self.db.commit()
        log_event(logger, "profile_report", profile_user_id=profile_user_id, reporter_id=reporter.id)

    async def list_profile_reports(self, moderator: User, status: ReportStatus, page: int, page_size: int):
        if not is_moderator(moderator):
            raise ModerationError("Moderators only.", 403)
        total = await self.db.scalar(select(func.count()).select_from(ProfileReport).where(ProfileReport.status == status)) or 0
        rows = (
            await self.db.execute(
                select(ProfileReport, User)
                .join(User, User.id == ProfileReport.profile_user_id)
                .where(ProfileReport.status == status)
                .order_by(ProfileReport.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return [
            ProfileReportOut(
                id=r.id, profile_user_id=u.id, display_name=u.display_name or "Fan", reason=r.reason, status=r.status,
                created_at=r.created_at, suspended=u.suspended_at is not None,
            )
            for r, u in rows
        ], total

    async def resolve_profile_report(self, moderator: User, report_id: int, action: str) -> None:
        if not is_moderator(moderator):
            raise ModerationError("Moderators only.", 403)
        report = await self.db.get(ProfileReport, report_id)
        if report is None:
            raise ModerationError("Report not found", 404)
        if action not in ("resolve", "dismiss"):
            raise ModerationError("Unknown action", 422)
        report.status = ReportStatus.RESOLVED if action == "resolve" else ReportStatus.DISMISSED
        report.resolved_by, report.resolved_at = moderator.id, datetime.now(timezone.utc)
        audit.record(self.db, action=f"profile_report.{action}", target_type="profile_report", target_id=report_id, actor=moderator)
        await self.db.commit()

    async def suspend(self, admin: User, user_id: int, reason: str) -> None:
        if admin.role != UserRole.ADMIN:
            raise ModerationError("Only admins can suspend accounts.", 403)
        target = await self.db.get(User, user_id)
        if target is None:
            raise ModerationError("User not found", 404)
        if target.id == admin.id or target.role == UserRole.ADMIN:
            raise ModerationError("That account can't be suspended.", 400)
        target.suspended_at = datetime.now(timezone.utc)
        target.suspended_reason = reason.strip()[:200] or None
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == target.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        audit.record(self.db, action="user.suspend", target_type="user", target_id=target.id, actor=admin, reason=reason)
        await self.db.commit()
        log_event(logger, "user_suspended", user_id=target.id, admin_id=admin.id)

    async def unsuspend(self, admin: User, user_id: int) -> None:
        if admin.role != UserRole.ADMIN:
            raise ModerationError("Only admins can restore accounts.", 403)
        target = await self.db.get(User, user_id)
        if target is None:
            raise ModerationError("User not found", 404)
        target.suspended_at, target.suspended_reason = None, None
        audit.record(self.db, action="user.unsuspend", target_type="user", target_id=target.id, actor=admin)
        await self.db.commit()
        log_event(logger, "user_unsuspended", user_id=target.id, admin_id=admin.id)
