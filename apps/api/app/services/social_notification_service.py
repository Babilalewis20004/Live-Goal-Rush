"""Community and editorial notifications (Phase 6): comment replies, poll
results, editorial updates (review requested / approved / rejected / scheduled).

Same pipeline as article and match notifications -- the Phase 3 device registry
and push senders -- with the same three rules:

* **Preferences**: each kind is a `ContentNotificationKind` the user can switch
  on or off (`/notifications/content-preferences`). Replies to your own comment and
  updates about your own articles default **on** (they are about *your* actions);
  poll results default **off**.
* **Idempotent**: `(user_id, dedup_key)` is unique in `social_notification_log`; the
  claim and the send are separate steps, so a retried Celery task never sends twice.
* **Quiet**: you are never notified about your own action.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging_config import log_event
from app.models.article import Article
from app.models.community import Comment, Poll, PollVote, SocialNotificationLog
from app.models.content_notification import ContentNotificationPreference
from app.models.enums import (
    ArticleStatus,
    CommentStatus,
    CommentTarget,
    ContentNotificationKind,
    PollStatus,
    UserRole,
)
from app.models.user import User
from app.services.content_notification_service import CONTENT_DEFAULTS
from app.services.notifications.base import NotificationPayload
from app.services.notifications.service import NotificationService

logger = logging.getLogger(__name__)


def _body(text: str, limit: int = 120) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


async def wanting(db: AsyncSession, user_ids: set[int], kind: ContentNotificationKind) -> set[int]:
    """Users in `user_ids` for whom `kind` is switched on (explicitly, or by default)."""
    if not user_ids:
        return set()
    rows = await db.execute(
        select(ContentNotificationPreference.user_id, ContentNotificationPreference.enabled).where(
            ContentNotificationPreference.kind == kind, ContentNotificationPreference.user_id.in_(user_ids)
        )
    )
    explicit = {uid: enabled for uid, enabled in rows}
    return {uid for uid in user_ids if explicit.get(uid, CONTENT_DEFAULTS[kind])}


async def _claim(db: AsyncSession, user_ids: set[int], dedup_key: str) -> set[int]:
    if not user_ids:
        return set()
    result = await db.execute(
        pg_insert(SocialNotificationLog)
        .values([{"user_id": uid, "dedup_key": dedup_key} for uid in user_ids])
        .on_conflict_do_nothing(index_elements=["user_id", "dedup_key"])
        .returning(SocialNotificationLog.user_id)
    )
    claimed = {row[0] for row in result}
    await db.commit()
    return claimed


async def deliver(
    db: AsyncSession,
    user_ids: set[int],
    kind: ContentNotificationKind,
    dedup_key: str,
    title: str,
    body: str,
    data: dict,
    *,
    service: NotificationService | None = None,
) -> int:
    """Send one notification to each eligible user, once. Returns how many were sent."""
    eligible = await wanting(db, user_ids, kind)
    claimed = await _claim(db, eligible, dedup_key)
    if not claimed:
        return 0
    service = service or NotificationService(db)
    payload = NotificationPayload(title=title, body=_body(body), data=data)
    for user_id in claimed:
        await service.send_payload_to_user(user_id, payload)
    log_event(logger, "social_notification", kind=kind.value, recipients=len(claimed), dedup_key=dedup_key)
    return len(claimed)


# -- the three notification flows (the Celery tasks are thin wrappers around these) ---------------


async def notify_comment_reply(db: AsyncSession, comment_id: int, *, service: NotificationService | None = None) -> int:
    reply = await db.scalar(select(Comment).where(Comment.id == comment_id).options(selectinload(Comment.user)))
    if reply is None or reply.parent_id is None or reply.status != CommentStatus.VISIBLE:
        return 0
    parent = await db.get(Comment, reply.parent_id)
    if parent is None or parent.user_id == reply.user_id or parent.status == CommentStatus.DELETED:
        return 0  # never notify yourself, or about a comment that is gone
    if reply.target_type == CommentTarget.ARTICLE:
        slug = await db.scalar(select(Article.slug).where(Article.id == reply.target_id))
        if slug is None:
            return 0
        data = {"type": "article", "id": slug}
    else:
        data = {"type": "match", "id": reply.target_id}
    name = reply.user.display_name or "Someone"
    return await deliver(
        db, {parent.user_id}, ContentNotificationKind.COMMENT_REPLIES, f"reply:{reply.id}",
        f"{name} replied to your comment", reply.body, data, service=service,
    )


async def notify_editorial(db: AsyncSession, article_id: int, event: str, *, service: NotificationService | None = None) -> int:
    """submitted -> every editor/admin except the submitter; published / scheduled /
    rejected -> the article's author."""
    article = await db.get(Article, article_id)
    if article is None:
        return 0
    kind = ContentNotificationKind.EDITORIAL_UPDATES
    key = f"editorial:{article.id}:{event}:{int(article.updated_at.timestamp())}"
    if event == "submitted":
        if article.status != ArticleStatus.IN_REVIEW:
            return 0
        reviewers = set(
            (await db.execute(select(User.id).where(User.role.in_([UserRole.EDITOR, UserRole.ADMIN]), User.is_active.is_(True)))).scalars()
        )
        reviewers.discard(article.author_id)
        return await deliver(db, reviewers, kind, key, "Article awaiting review", article.title, {"type": "editor", "id": article.id}, service=service)
    if article.author_id is None:
        return 0
    if event == "published" and article.status == ArticleStatus.PUBLISHED:
        return await deliver(db, {article.author_id}, kind, key, "Your article is live", article.title, {"type": "article", "id": article.slug}, service=service)
    if event == "scheduled" and article.status == ArticleStatus.SCHEDULED:
        return await deliver(db, {article.author_id}, kind, key, "Your article is scheduled", article.title, {"type": "editor", "id": article.id}, service=service)
    if event == "rejected" and article.status == ArticleStatus.DRAFT:
        return await deliver(db, {article.author_id}, kind, key, "Changes requested", article.review_note or article.title, {"type": "editor", "id": article.id}, service=service)
    return 0


async def notify_poll_results(db: AsyncSession, poll_id: int, *, service: NotificationService | None = None) -> int:
    """Once per poll, after it closes: tell the people who voted what won."""
    claimed = await db.execute(
        update(Poll)
        .where(Poll.id == poll_id, Poll.status == PollStatus.CLOSED, Poll.results_notified_at.is_(None))
        .values(results_notified_at=func.now())
        .returning(Poll.id)
    )
    if claimed.scalar_one_or_none() is None:
        await db.rollback()
        return 0  # already announced, or not closed
    await db.commit()
    poll = await db.scalar(select(Poll).where(Poll.id == poll_id).options(selectinload(Poll.options)))
    voters = set((await db.execute(select(PollVote.user_id).where(PollVote.poll_id == poll_id))).scalars())
    if poll is None or not voters:
        return 0
    counts = dict((await db.execute(select(PollVote.option_id, func.count()).where(PollVote.poll_id == poll_id).group_by(PollVote.option_id))).all())
    total = sum(counts.values())
    best = max(poll.options, key=lambda o: (counts.get(o.id, 0), -o.position))
    share = round(100 * counts.get(best.id, 0) / total) if total else 0
    if poll.article_id:
        slug = await db.scalar(select(Article.slug).where(Article.id == poll.article_id))
        data = {"type": "article", "id": slug} if slug else {"type": "poll", "id": poll.id}
    elif poll.match_id:
        data = {"type": "match", "id": poll.match_id}
    else:
        data = {"type": "poll", "id": poll.id}
    return await deliver(
        db, voters, ContentNotificationKind.POLL_RESULTS, f"poll:{poll.id}", "Poll results are in",
        f"{poll.question} — {best.label} ({share}%)", data, service=service,
    )
