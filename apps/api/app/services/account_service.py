"""Account deletion and personal-data export (Phase 7, privacy).

Deletion is **erasure of personal data, not deletion of the row**. The `users` row stays as an anonymous
tombstone (`deleted-<id>@deleted.invalid`, no password, inactive) for one reason: subscription and payment
records must be retained for tax/accounting and chargeback handling, and they reference the user. Everything
else the person created or that identifies them is removed (see docs/security/data-inventory.md):

    deleted        sessions, reset tokens, devices/push endpoints, favourites, notification settings and
                   history, recent searches, reactions, comment likes, poll votes, reports they filed,
                   operator-granted entitlements
    anonymised     comments (text replaced, thread structure kept so replies stay readable)
    retained       subscriptions + payment events (legal), the audit log (security), moderation outcomes

Staff accounts (author/editor/admin) cannot erase themselves: their content and permissions need an operator
hand-over first, and it prevents the last administrator locking everyone out.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.billing import Entitlement, Subscription, SubscriptionPlan
from app.models.community import Comment, CommentLike, CommentReport, PollVote, ProfileReport, Reaction, SocialNotificationLog
from app.models.content_notification import ContentNotificationLog, ContentNotificationPreference
from app.models.device import Device
from app.models.engagement import RecentSearch
from app.models.enums import CommentStatus, UserRole
from app.models.favourite import FavouriteCompetition, FavouriteMatch, FavouriteTeam
from app.models.notification import NotificationLog, NotificationPreference
from app.models.session import PasswordResetToken, RefreshToken
from app.models.user import User
from app.services import audit_service as audit
from app.services.billing.service import BillingError, BillingService
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

DELETED_COMMENT_BODY = "[deleted]"


class AccountError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def delete_account(db: AsyncSession, user: User, password: str, billing: BillingService | None = None) -> None:
    if user.role != UserRole.USER:
        raise AccountError("Staff accounts must be handed over by an administrator before they can be deleted.", 403)
    if not verify_password(password, user.hashed_password):
        raise AccountError("Password is incorrect.", 400)

    # Stop the money first: if the processor cannot be told, deleting the account would leave a live
    # subscription billing someone who can no longer sign in. The user can simply retry.
    if billing is not None:
        try:
            await billing.cancel(user)
        except BillingError as exc:
            if exc.status_code != 404:  # 404 = nothing to cancel
                raise AccountError("We could not cancel your subscription with the payment provider. Please try again shortly.", 502) from exc

    uid = user.id
    for model in (
        RefreshToken, PasswordResetToken, Device, FavouriteTeam, FavouriteCompetition, FavouriteMatch,
        NotificationPreference, NotificationLog, ContentNotificationPreference, ContentNotificationLog,
        RecentSearch, Reaction, CommentLike, PollVote, SocialNotificationLog, Entitlement,
    ):
        await db.execute(delete(model).where(model.user_id == uid))
    await db.execute(delete(CommentReport).where(CommentReport.reporter_id == uid))
    await db.execute(delete(ProfileReport).where((ProfileReport.reporter_id == uid) | (ProfileReport.profile_user_id == uid)))
    await db.execute(
        update(Comment)
        .where(Comment.user_id == uid)
        .values(body=DELETED_COMMENT_BODY, status=CommentStatus.DELETED, edited_at=datetime.now(timezone.utc))
    )

    user.email = f"deleted-{uid}@deleted.invalid"
    user.hashed_password = hash_password(secrets.token_urlsafe(32))  # unusable: nobody knows it
    user.display_name = None
    user.bio = None
    user.is_active = False
    user.profile_public = False
    user.suspended_at = None
    user.suspended_reason = None
    user.deleted_at = datetime.now(timezone.utc)
    audit.record(db, action="account.delete", target_type="user", target_id=uid, actor=user)
    await db.commit()
    metrics.count("account_deletions_total")
    logger.info("Account erased user_id=%s", uid)


async def export_user_data(db: AsyncSession, user: User) -> dict[str, Any]:
    """Everything the person has given us or created, as plain JSON. Excludes credentials (password hash, tokens,
    push endpoints), internal security data (IP addresses, audit entries), payment-processor identifiers, and
    anything about other people."""
    uid = user.id

    async def rows(model, *columns, where=None):
        stmt = select(*[getattr(model, c) for c in columns]).where(where if where is not None else model.user_id == uid)
        return [dict(zip(columns, _plain(r))) for r in (await db.execute(stmt)).all()]

    subscriptions = (
        await db.execute(
            select(Subscription, SubscriptionPlan.code)
            .join(SubscriptionPlan, SubscriptionPlan.id == Subscription.plan_id)
            .where(Subscription.user_id == uid)
        )
    ).all()
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            "id": uid,
            "email": user.email,
            "display_name": user.display_name,
            "bio": user.bio,
            "role": user.role.value,
            "profile_public": user.profile_public,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "favourites": {
            "teams": [r[0] for r in (await db.execute(select(FavouriteTeam.team_id).where(FavouriteTeam.user_id == uid))).all()],
            "competitions": [r[0] for r in (await db.execute(select(FavouriteCompetition.competition_id).where(FavouriteCompetition.user_id == uid))).all()],
            "matches": [r[0] for r in (await db.execute(select(FavouriteMatch.match_id).where(FavouriteMatch.user_id == uid))).all()],
        },
        "notification_preferences": await rows(NotificationPreference, "scope_type", "scope_id", "event_type", "enabled"),
        "content_notification_preferences": await rows(ContentNotificationPreference, "kind", "enabled"),
        "devices": await rows(Device, "platform", "created_at", "last_seen_at"),
        "recent_searches": await rows(RecentSearch, "query", "last_searched_at"),
        "comments": await rows(Comment, "id", "target_type", "target_id", "parent_id", "body", "status", "created_at"),
        "reactions": await rows(Reaction, "target_type", "target_id", "kind", "created_at"),
        "poll_votes": await rows(PollVote, "poll_id", "option_id", "created_at"),
        "subscriptions": [
            {
                "plan": code,
                "status": sub.status.value,
                "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
                "cancel_at_period_end": sub.cancel_at_period_end,
                "started_at": sub.created_at.isoformat() if sub.created_at else None,
            }
            for sub, code in subscriptions
        ],
        "entitlements": await rows(Entitlement, "key", "source", "expires_at"),
    }


def _plain(row) -> list[Any]:
    out = []
    for value in row:
        if isinstance(value, datetime):
            out.append(value.isoformat())
        elif hasattr(value, "value"):  # enum
            out.append(value.value)
        else:
            out.append(value)
    return out
