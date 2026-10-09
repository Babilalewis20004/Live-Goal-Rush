"""Comments, reactions and polls (Phase 6).

PostgreSQL is the source of truth for all three. Redis holds only things that
can be rebuilt from it and that are read far more often than written:

* comment *pages* (viewer-independent JSON, versioned per target, 30 s TTL);
* reaction counts and poll vote counts (hashes updated incrementally; a missing
  or expired hash is rebuilt from the database, which also bounds any drift).

Abuse resistance, in layers: authentication is required to write anything;
per-user Redis rate limits; length and link limits (links need an account
older than ten minutes); duplicate suppression; one reaction / one vote per user
enforced by unique constraints; and community reports that hide a comment for
review after several independent reporters.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.events.community import publish_match_event
from app.events.schemas import RealtimeEventType
from app.core.logging_config import log_event
from app.services import audit_service as audit
from app.core.redis_client import RedisService
from app.models.article import Article
from app.models.community import Comment, CommentLike, CommentReport, Poll, PollOption, PollVote, Reaction
from app.models.enums import (
    ArticleStatus,
    CommentStatus,
    CommentTarget,
    PollKind,
    PollStatus,
    ReactionKind,
    ReactionTarget,
    ReportStatus,
    UserRole,
)
from app.models.match import Match
from app.models.user import User
from app.schemas.community import (
    CommentAuthor,
    CommentOut,
    CommentPage,
    PollIn,
    PollOptionOut,
    PollOut,
    ReactionSummary,
    ReportOut,
)
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

_LINK = re.compile(r"(https?://|www\.)", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ACCOUNT_AGE_FOR_LINKS = timedelta(minutes=10)
_DUPLICATE_WINDOW = timedelta(minutes=5)
_REACTION_TTL = 600  # seconds; bounds drift between the Redis hash and PostgreSQL
_POLL_TTL = 3600


class CommunityError(Exception):
    status_code = 400


class NotFound(CommunityError):
    status_code = 404


class Forbidden(CommunityError):
    status_code = 403


class Invalid(CommunityError):
    status_code = 422


class Conflict(CommunityError):
    status_code = 409


class RateLimited(CommunityError):
    status_code = 429


def is_moderator(user: User) -> bool:
    return user.role in (UserRole.EDITOR, UserRole.ADMIN)


async def _rate_limit(redis: RedisService | None, bucket: str, user_id: int, limit: int, window: int) -> None:
    if redis is None:
        return
    try:
        count = await redis.incr(f"ratelimit:{bucket}:{user_id}", ttl_seconds=window)
    except Exception:
        return  # fail open, like every limiter in this codebase
    if count > limit:
        raise RateLimited("You're doing that too fast. Please wait a moment.")


async def _target_exists(db: AsyncSession, target_type: str, target_id: int) -> None:
    """Comments and reactions attach to a real, public thing."""
    if target_type == "article":
        found = await db.scalar(
            select(Article.id).where(
                Article.id == target_id,
                Article.status == ArticleStatus.PUBLISHED,
                Article.published_at <= func.now(),
                or_(Article.unpublish_at.is_(None), Article.unpublish_at > func.now()),
            )
        )
    else:
        found = await db.scalar(select(Match.id).where(Match.id == target_id))
    if found is None:
        raise NotFound(f"{target_type.capitalize()} not found")


def _display_name(user: User) -> str:
    return (user.display_name or "Fan").strip()[:100] or "Fan"


# ===================================================================================
# Comments
# ===================================================================================


class CommentService:
    def __init__(self, db: AsyncSession, redis: RedisService | None = None) -> None:
        self.db = db
        self.redis = redis

    # -- cache version per target --------------------------------------------------

    def _ver_key(self, target_type: str, target_id: int) -> str:
        return f"football:comments:ver:{target_type}:{target_id}"

    async def _version(self, target_type: str, target_id: int) -> str:
        if self.redis is None:
            return "0"
        try:
            return str(await self.redis.raw.get(self._ver_key(target_type, target_id)) or "0")
        except Exception:
            return "0"

    async def _bump(self, target_type: str, target_id: int) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.raw.incr(self._ver_key(target_type, target_id))
        except Exception:
            logger.warning("Could not bump comment cache version", exc_info=True)

    # -- reading ---------------------------------------------------------------------

    @staticmethod
    def _out(comment: Comment, *, removed: bool, reply_count: int = 0) -> CommentOut:
        author = None
        if not removed:
            author = CommentAuthor(
                id=comment.user.id, display_name=_display_name(comment.user), profile_public=comment.user.profile_public
            )
        return CommentOut(
            id=comment.id,
            author=author,
            body="" if removed else comment.body,
            created_at=comment.created_at,
            edited_at=comment.edited_at,
            like_count=0 if removed else comment.like_count,
            reply_count=reply_count,
            removed=removed,
            parent_id=comment.parent_id,
        )

    async def _load_page(self, target_type: CommentTarget, target_id: int, sort: str, page: int, page_size: int) -> CommentPage:
        reply_alias = Comment.__table__.alias("r")
        parent_has_replies = exists().where(
            reply_alias.c.parent_id == Comment.id, reply_alias.c.status == CommentStatus.VISIBLE.name
        )
        top_where = and_(
            Comment.target_type == target_type,
            Comment.target_id == target_id,
            Comment.parent_id.is_(None),
            or_(Comment.status == CommentStatus.VISIBLE, parent_has_replies),
        )
        total = (await self.db.execute(select(func.count()).select_from(Comment).where(top_where))).scalar_one()
        total_comments = (
            await self.db.execute(
                select(func.count()).select_from(Comment).where(
                    Comment.target_type == target_type, Comment.target_id == target_id, Comment.status == CommentStatus.VISIBLE
                )
            )
        ).scalar_one()
        order = (Comment.like_count.desc(), Comment.created_at.desc()) if sort == "top" else (Comment.created_at.desc(), Comment.id.desc())
        tops = (
            await self.db.execute(
                select(Comment).where(top_where).options(selectinload(Comment.user)).order_by(*order)
                .offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        replies_by_parent: dict[int, list[Comment]] = {}
        if tops:
            replies = (
                await self.db.execute(
                    select(Comment)
                    .where(Comment.parent_id.in_([c.id for c in tops]), Comment.status == CommentStatus.VISIBLE)
                    .options(selectinload(Comment.user))
                    .order_by(Comment.created_at.asc(), Comment.id.asc())
                    .limit(500)
                )
            ).scalars().all()
            for r in replies:
                replies_by_parent.setdefault(r.parent_id, []).append(r)
        items = []
        for c in tops:
            kids = replies_by_parent.get(c.id, [])
            node = self._out(c, removed=c.status != CommentStatus.VISIBLE, reply_count=len(kids))
            node.replies = [self._out(k, removed=False) for k in kids]
            items.append(node)
        return CommentPage(items=items, total=total, total_comments=total_comments, page=page, page_size=page_size)

    async def list(
        self, target_type: CommentTarget, target_id: int, *, sort: str = "newest", page: int = 1, page_size: int = 20, viewer: User | None = None
    ) -> CommentPage:
        await _target_exists(self.db, target_type.value, target_id)
        cache_key = f"football:comments:{target_type.value}:{target_id}:{await self._version(target_type.value, target_id)}:{sort}:{page}:{page_size}"
        result: CommentPage | None = None
        if self.redis is not None:
            try:
                cached = await self.redis.get(cache_key)
                if cached is not None:
                    result = CommentPage.model_validate(cached)
                    metrics.cache_hit()
            except Exception:
                result = None
        if result is None:
            metrics.cache_miss()
            result = await self._load_page(target_type, target_id, sort, page, page_size)
            if self.redis is not None:
                try:
                    await self.redis.set(cache_key, result.model_dump(mode="json"), ttl_seconds=settings.comment_cache_ttl_seconds)
                except Exception:
                    pass
        # viewer-specific overlay, never cached
        if viewer is not None:
            nodes = [n for top in result.items for n in (top, *top.replies)]
            liked = set(
                (await self.db.execute(select(CommentLike.comment_id).where(CommentLike.user_id == viewer.id, CommentLike.comment_id.in_([n.id for n in nodes])))).scalars()
            ) if nodes else set()
            for n in nodes:
                n.liked_by_me = n.id in liked
                n.mine = n.author is not None and n.author.id == viewer.id
        return result

    # -- writing ---------------------------------------------------------------------

    def _clean(self, body: str, user: User) -> str:
        text = _CONTROL.sub("", body).replace("\r\n", "\n").strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        if not text:
            raise Invalid("Write something first.")
        if len(text) > settings.comment_max_length:
            raise Invalid(f"Comments are limited to {settings.comment_max_length} characters.")
        links = len(_LINK.findall(text))
        if links > settings.comment_max_links:
            raise Invalid(f"Please include at most {settings.comment_max_links} links.")
        created = user.created_at if user.created_at.tzinfo else user.created_at.replace(tzinfo=timezone.utc)
        if links and datetime.now(timezone.utc) - created < _ACCOUNT_AGE_FOR_LINKS:
            raise Invalid("New accounts can't post links yet. Try again in a few minutes.")
        return text

    async def create(self, user: User, target_type: CommentTarget, target_id: int, body: str, parent_id: int | None = None) -> Comment:
        text = self._clean(body, user)
        await _target_exists(self.db, target_type.value, target_id)
        await _rate_limit(self.redis, "comment-min", user.id, settings.comments_per_minute, 60)
        await _rate_limit(self.redis, "comment-hour", user.id, settings.comments_per_hour, 3600)
        if parent_id is not None:
            parent = await self.db.get(Comment, parent_id)
            if parent is None or parent.target_type != target_type or parent.target_id != target_id or parent.status != CommentStatus.VISIBLE:
                raise Invalid("You can't reply to that comment.")
            parent_id = parent.parent_id or parent.id  # replies stay one level deep
        duplicate = await self.db.scalar(
            select(Comment.id).where(
                Comment.user_id == user.id,
                Comment.target_type == target_type,
                Comment.target_id == target_id,
                func.lower(Comment.body) == text.lower(),
                Comment.created_at > func.now() - _DUPLICATE_WINDOW,
                Comment.status != CommentStatus.DELETED,
            )
        )
        if duplicate:
            raise Invalid("You already posted that.")
        comment = Comment(user_id=user.id, target_type=target_type, target_id=target_id, parent_id=parent_id, body=text)
        self.db.add(comment)
        await self.db.commit()
        await self.db.refresh(comment, attribute_names=["user"])
        await self._bump(target_type.value, target_id)
        metrics.comment_created()
        if target_type == CommentTarget.MATCH:
            await publish_match_event(self.redis, RealtimeEventType.COMMENT_CREATED, target_id, comment_id=comment.id, parent_id=parent_id)
        log_event(logger, "comment_create", comment_id=comment.id, user_id=user.id, target_type=target_type.value, target_id=target_id, reply=parent_id is not None)
        return comment

    async def _own(self, user: User, comment_id: int) -> Comment:
        comment = await self.db.scalar(select(Comment).where(Comment.id == comment_id).options(selectinload(Comment.user)))
        if comment is None or comment.status == CommentStatus.DELETED:
            raise NotFound("Comment not found")
        return comment

    async def edit(self, user: User, comment_id: int, body: str) -> Comment:
        comment = await self._own(user, comment_id)
        if comment.user_id != user.id:
            raise Forbidden("You can only edit your own comments.")
        if comment.status != CommentStatus.VISIBLE:
            raise Forbidden("This comment can't be edited.")
        text = self._clean(body, user)
        if text == comment.body:
            return comment
        comment.body = text
        comment.edited_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self._bump(comment.target_type.value, comment.target_id)
        log_event(logger, "comment_edit", comment_id=comment.id, user_id=user.id)
        return comment

    async def delete(self, user: User, comment_id: int) -> None:
        comment = await self._own(user, comment_id)
        if comment.user_id != user.id and not is_moderator(user):
            raise Forbidden("You can only delete your own comments.")
        comment.status = CommentStatus.DELETED
        if comment.user_id != user.id:
            comment.moderated_by, comment.moderated_at = user.id, datetime.now(timezone.utc)
        await self._resolve_reports(comment.id, user.id, ReportStatus.RESOLVED)
        await self.db.commit()
        await self._bump(comment.target_type.value, comment.target_id)
        log_event(logger, "comment_delete", comment_id=comment.id, user_id=user.id, moderator=comment.user_id != user.id)

    async def like(self, user: User, comment_id: int, liked: bool) -> int:
        comment = await self._own(user, comment_id)
        if comment.status != CommentStatus.VISIBLE:
            raise NotFound("Comment not found")
        await _rate_limit(self.redis, "comment-like", user.id, 60, 60)
        if liked:
            inserted = await self.db.execute(
                pg_insert(CommentLike).values(comment_id=comment_id, user_id=user.id).on_conflict_do_nothing(index_elements=["comment_id", "user_id"]).returning(CommentLike.id)
            )
            if inserted.scalar_one_or_none() is not None:
                await self.db.execute(update(Comment).where(Comment.id == comment_id).values(like_count=Comment.like_count + 1))
        else:
            removed = await self.db.execute(delete(CommentLike).where(CommentLike.comment_id == comment_id, CommentLike.user_id == user.id).returning(CommentLike.id))
            if removed.scalar_one_or_none() is not None:
                await self.db.execute(update(Comment).where(Comment.id == comment_id).values(like_count=func.greatest(Comment.like_count - 1, 0)))
        await self.db.commit()
        return (await self.db.execute(select(Comment.like_count).where(Comment.id == comment_id))).scalar_one()

    async def report(self, user: User, comment_id: int, reason: str) -> None:
        comment = await self._own(user, comment_id)
        if comment.user_id == user.id:
            raise Invalid("You can't report your own comment.")
        if comment.status != CommentStatus.VISIBLE:
            raise NotFound("Comment not found")
        await _rate_limit(self.redis, "comment-report", user.id, 10, 3600)
        inserted = await self.db.execute(
            pg_insert(CommentReport)
            .values(comment_id=comment_id, reporter_id=user.id, reason=reason.strip()[:200])
            .on_conflict_do_nothing(index_elements=["comment_id", "reporter_id"])
            .returning(CommentReport.id)
        )
        if inserted.scalar_one_or_none() is None:
            await self.db.rollback()
            return  # already reported by this user: idempotent
        comment.report_count += 1
        hidden = False
        if comment.report_count >= settings.comment_auto_hide_reports:
            comment.status = CommentStatus.HIDDEN  # pending review; a moderator can restore it
            hidden = True
        await self.db.commit()
        metrics.comment_reported()
        if hidden:
            await self._bump(comment.target_type.value, comment.target_id)
        log_event(logger, "comment_report", comment_id=comment.id, user_id=user.id, auto_hidden=hidden)

    # -- moderation ------------------------------------------------------------------------

    async def _resolve_reports(self, comment_id: int, moderator_id: int, status: ReportStatus) -> None:
        await self.db.execute(
            update(CommentReport)
            .where(CommentReport.comment_id == comment_id, CommentReport.status == ReportStatus.OPEN)
            .values(status=status, resolved_by=moderator_id, resolved_at=func.now())
        )

    async def list_reports(self, moderator: User, status: ReportStatus, page: int, page_size: int) -> tuple[list[ReportOut], int]:
        if not is_moderator(moderator):
            raise Forbidden("Moderators only.")
        total = (await self.db.execute(select(func.count()).select_from(CommentReport).where(CommentReport.status == status))).scalar_one()
        rows = (
            await self.db.execute(
                select(CommentReport, Comment, User.display_name)
                .join(Comment, Comment.id == CommentReport.comment_id)
                .join(User, User.id == Comment.user_id)
                .where(CommentReport.status == status)
                .order_by(CommentReport.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return [
            ReportOut(
                id=r.id, comment_id=c.id, comment_body=c.body, comment_status=c.status, comment_author=name or "Fan",
                target_type=c.target_type, target_id=c.target_id, reason=r.reason, status=r.status, created_at=r.created_at,
                report_count=c.report_count,
            )
            for r, c, name in rows
        ], total

    async def moderate(self, moderator: User, comment_id: int, action: str) -> Comment:
        if not is_moderator(moderator):
            raise Forbidden("Moderators only.")
        comment = await self.db.scalar(select(Comment).where(Comment.id == comment_id).options(selectinload(Comment.user)))
        if comment is None:
            raise NotFound("Comment not found")
        if action == "hide":
            comment.status, outcome = CommentStatus.HIDDEN, ReportStatus.RESOLVED
        elif action == "delete":
            comment.status, outcome = CommentStatus.DELETED, ReportStatus.RESOLVED
        elif action == "restore":
            comment.status, outcome = CommentStatus.VISIBLE, ReportStatus.DISMISSED
            comment.report_count = 0
        else:
            raise Invalid("Unknown action")
        comment.moderated_by, comment.moderated_at = moderator.id, datetime.now(timezone.utc)
        await self._resolve_reports(comment.id, moderator.id, outcome)
        audit.record(self.db, action=f"comment.{action}", target_type="comment", target_id=comment.id, actor=moderator, details={"author_id": comment.user_id})
        await self.db.commit()
        await self._bump(comment.target_type.value, comment.target_id)
        log_event(logger, "comment_moderate", comment_id=comment.id, moderator_id=moderator.id, action=action)
        return comment


# ===================================================================================
# Reactions
# ===================================================================================

_KINDS = [k.value for k in ReactionKind]


class ReactionService:
    def __init__(self, db: AsyncSession, redis: RedisService | None = None) -> None:
        self.db = db
        self.redis = redis

    @staticmethod
    def _key(target_type: str, target_id: int) -> str:
        return f"football:reactions:{target_type}:{target_id}"

    async def _db_counts(self, target_type: ReactionTarget, target_id: int) -> dict[str, int]:
        rows = await self.db.execute(
            select(Reaction.kind, func.count()).where(Reaction.target_type == target_type, Reaction.target_id == target_id).group_by(Reaction.kind)
        )
        counts = dict.fromkeys(_KINDS, 0)
        for kind, n in rows:
            counts[kind.value] = n
        return counts

    async def counts(self, target_type: ReactionTarget, target_id: int) -> dict[str, int]:
        """From the Redis hash; rebuilt from PostgreSQL when it is missing/expired
        (or Redis is down, in which case straight from PostgreSQL)."""
        key = self._key(target_type.value, target_id)
        if self.redis is not None:
            try:
                raw = await self.redis.raw.hgetall(key)
                if raw and "_" in raw:
                    metrics.cache_hit()
                    return {k: max(int(raw.get(k, 0)), 0) for k in _KINDS}
            except Exception:
                pass
        metrics.cache_miss()
        counts = await self._db_counts(target_type, target_id)
        if self.redis is not None:
            try:
                pipe = self.redis.raw.pipeline()
                pipe.delete(key)
                pipe.hset(key, mapping={"_": 1, **counts})
                pipe.expire(key, _REACTION_TTL)
                await pipe.execute()
            except Exception:
                pass
        return counts

    async def summary(self, target_type: ReactionTarget, target_id: int, viewer: User | None) -> ReactionSummary:
        await _target_exists(self.db, target_type.value, target_id)
        counts = await self.counts(target_type, target_id)
        mine = None
        if viewer is not None:
            mine = await self.db.scalar(
                select(Reaction.kind).where(Reaction.user_id == viewer.id, Reaction.target_type == target_type, Reaction.target_id == target_id)
            )
        return ReactionSummary(counts=counts, total=sum(counts.values()), mine=mine)

    async def _adjust(self, target_type: str, target_id: int, kind: str, delta: int) -> None:
        if self.redis is None:
            return
        try:
            key = self._key(target_type, target_id)
            if await self.redis.raw.exists(key):  # if absent, the next read rebuilds from the database
                await self.redis.raw.hincrby(key, kind, delta)
        except Exception:
            pass

    async def react(self, user: User, target_type: ReactionTarget, target_id: int, kind: ReactionKind) -> ReactionSummary:
        await _target_exists(self.db, target_type.value, target_id)
        await _rate_limit(self.redis, "reaction", user.id, settings.reactions_per_minute, 60)
        existing = await self.db.scalar(
            select(Reaction).where(Reaction.user_id == user.id, Reaction.target_type == target_type, Reaction.target_id == target_id)
        )
        if existing is not None and existing.kind == kind:
            return await self.summary(target_type, target_id, user)  # idempotent
        previous = existing.kind if existing is not None else None
        try:
            if existing is not None:
                existing.kind = kind
            else:
                self.db.add(Reaction(user_id=user.id, target_type=target_type, target_id=target_id, kind=kind))
            await self.db.commit()
        except IntegrityError:  # two quick taps raced: the unique constraint won, the result is the same
            await self.db.rollback()
            return await self.summary(target_type, target_id, user)
        if previous is not None:
            await self._adjust(target_type.value, target_id, previous.value, -1)
        await self._adjust(target_type.value, target_id, kind.value, +1)
        metrics.reaction_recorded()
        if target_type == ReactionTarget.MATCH:
            await publish_match_event(self.redis, RealtimeEventType.COMMENT_REACTION, target_id)
        return await self.summary(target_type, target_id, user)

    async def remove(self, user: User, target_type: ReactionTarget, target_id: int) -> ReactionSummary:
        await _target_exists(self.db, target_type.value, target_id)
        removed = await self.db.execute(
            delete(Reaction)
            .where(Reaction.user_id == user.id, Reaction.target_type == target_type, Reaction.target_id == target_id)
            .returning(Reaction.kind)
        )
        kind = removed.scalar_one_or_none()
        await self.db.commit()
        if kind is not None:
            await self._adjust(target_type.value, target_id, kind.value, -1)
        return await self.summary(target_type, target_id, user)


# ===================================================================================
# Polls
# ===================================================================================


class PollService:
    def __init__(self, db: AsyncSession, redis: RedisService | None = None) -> None:
        self.db = db
        self.redis = redis

    @staticmethod
    def _key(poll_id: int) -> str:
        return f"football:poll:{poll_id}:counts"

    async def _db_counts(self, poll_id: int) -> dict[int, int]:
        rows = await self.db.execute(select(PollVote.option_id, func.count()).where(PollVote.poll_id == poll_id).group_by(PollVote.option_id))
        return {option_id: n for option_id, n in rows}

    async def _counts(self, poll: Poll) -> dict[int, int]:
        key = self._key(poll.id)
        if self.redis is not None:
            try:
                raw = await self.redis.raw.hgetall(key)
                if raw and "_" in raw:
                    return {o.id: max(int(raw.get(str(o.id), 0)), 0) for o in poll.options}
            except Exception:
                pass
        counts = await self._db_counts(poll.id)
        if self.redis is not None:
            try:
                pipe = self.redis.raw.pipeline()
                pipe.delete(key)
                pipe.hset(key, mapping={"_": 1, **{str(o.id): counts.get(o.id, 0) for o in poll.options}})
                pipe.expire(key, _POLL_TTL)
                await pipe.execute()
            except Exception:
                pass
        return {o.id: counts.get(o.id, 0) for o in poll.options}

    async def _out(self, poll: Poll, viewer: User | None) -> PollOut:
        counts = await self._counts(poll)
        total = sum(counts.values())
        my_vote = None
        if viewer is not None:
            my_vote = await self.db.scalar(select(PollVote.option_id).where(PollVote.poll_id == poll.id, PollVote.user_id == viewer.id))
        winner = None
        if poll.status == PollStatus.CLOSED and total:
            top = sorted(counts.values(), reverse=True)
            if len(top) == 1 or top[0] > top[1]:
                winner = max(counts, key=counts.get)
        return PollOut(
            id=poll.id, question=poll.question, kind=poll.kind, status=poll.status, match_id=poll.match_id, article_id=poll.article_id,
            closes_at=poll.closes_at, total_votes=total,
            options=[PollOptionOut(id=o.id, label=o.label, votes=counts[o.id], percent=round(100 * counts[o.id] / total, 1) if total else 0.0) for o in poll.options],
            my_vote=my_vote, winner_option_id=winner,
        )

    async def _get(self, poll_id: int) -> Poll:
        poll = await self.db.scalar(select(Poll).where(Poll.id == poll_id).options(selectinload(Poll.options)))
        if poll is None:
            raise NotFound("Poll not found")
        return poll

    async def get(self, poll_id: int, viewer: User | None) -> PollOut:
        return await self._out(await self._get(poll_id), viewer)

    async def list(self, *, match_id: int | None, article_id: int | None, status: PollStatus | None, standalone: bool, limit: int, viewer: User | None) -> list[PollOut]:
        clauses = []
        if match_id is not None:
            clauses.append(Poll.match_id == match_id)
        if article_id is not None:
            clauses.append(Poll.article_id == article_id)
        if standalone:
            clauses += [Poll.match_id.is_(None), Poll.article_id.is_(None)]
        if status is not None:
            clauses.append(Poll.status == status)
        polls = (
            await self.db.execute(select(Poll).where(*clauses).options(selectinload(Poll.options)).order_by(Poll.created_at.desc(), Poll.id.desc()).limit(limit))
        ).scalars().all()
        return [await self._out(p, viewer) for p in polls]

    async def create(self, editor: User, payload: PollIn) -> Poll:
        if not is_moderator(editor):
            raise Forbidden("Only editors can create polls.")
        labels = [" ".join(label.split()) for label in payload.options if label.strip()]
        match = None
        if payload.match_id is not None:
            match = await self.db.scalar(select(Match).where(Match.id == payload.match_id).options(selectinload(Match.home_team), selectinload(Match.away_team)))
            if match is None:
                raise Invalid("Unknown match")
        if payload.article_id is not None and await self.db.get(Article, payload.article_id) is None:
            raise Invalid("Unknown article")
        if not labels and payload.kind == PollKind.MATCH and match is not None:
            labels = [f"{match.home_team.name} win", "Draw", f"{match.away_team.name} win"]
        if not 2 <= len(labels) <= 6:
            raise Invalid("A poll needs between 2 and 6 options.")
        if len({label.lower() for label in labels}) != len(labels):
            raise Invalid("Options must be different from each other.")
        closes_at = payload.closes_at
        if closes_at is not None:
            closes_at = closes_at if closes_at.tzinfo else closes_at.replace(tzinfo=timezone.utc)
            if closes_at <= datetime.now(timezone.utc):
                raise Invalid("The closing time must be in the future.")
        poll = Poll(question=" ".join(payload.question.split()), kind=payload.kind, match_id=payload.match_id, article_id=payload.article_id, created_by=editor.id, closes_at=closes_at)
        poll.options = [PollOption(label=label[:100], position=i) for i, label in enumerate(labels)]
        self.db.add(poll)
        await self.db.commit()
        log_event(logger, "poll_create", poll_id=poll.id, user_id=editor.id, kind=poll.kind.value)
        return await self._get(poll.id)

    async def vote(self, user: User, poll_id: int, option_id: int) -> PollOut:
        poll = await self._get(poll_id)
        now = datetime.now(timezone.utc)
        if poll.status != PollStatus.OPEN or (poll.closes_at is not None and poll.closes_at <= now):
            raise Conflict("This poll is closed.")
        if option_id not in {o.id for o in poll.options}:
            raise Invalid("That option isn't part of this poll.")
        await _rate_limit(self.redis, "poll-vote", user.id, settings.poll_votes_per_minute, 60)
        try:
            self.db.add(PollVote(poll_id=poll_id, option_id=option_id, user_id=user.id))
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise Conflict("You have already voted in this poll.") from exc
        if self.redis is not None:
            try:
                key = self._key(poll_id)
                if await self.redis.raw.exists(key):
                    await self.redis.raw.hincrby(key, str(option_id), 1)
            except Exception:
                pass
        metrics.poll_voted()
        if poll.match_id:
            await publish_match_event(self.redis, RealtimeEventType.POLL_UPDATED, poll.match_id, poll_id=poll_id)
        log_event(logger, "poll_vote", poll_id=poll_id, user_id=user.id)
        return await self._out(poll, user)

    async def close(self, editor: User, poll_id: int) -> tuple[PollOut, bool]:
        """Returns (poll, newly_closed). Closing twice is a no-op."""
        if not is_moderator(editor):
            raise Forbidden("Only editors can close polls.")
        poll = await self._get(poll_id)
        newly = poll.status == PollStatus.OPEN
        if newly:
            poll.status, poll.closed_at = PollStatus.CLOSED, datetime.now(timezone.utc)
            await self.db.commit()
            log_event(logger, "poll_close", poll_id=poll.id, user_id=editor.id)
        return await self._out(poll, editor), newly

    async def close_due(self) -> list[int]:
        """Close every open poll whose `closes_at` has passed. One conditional
        UPDATE ... RETURNING, so concurrent or repeated runs close each poll once."""
        closed = list(
            (
                await self.db.execute(
                    update(Poll)
                    .where(Poll.status == PollStatus.OPEN, Poll.closes_at.is_not(None), Poll.closes_at <= func.now())
                    .values(status=PollStatus.CLOSED, closed_at=func.now())
                    .returning(Poll.id)
                )
            ).scalars()
        )
        await self.db.commit()
        for poll_id in closed:
            log_event(logger, "poll_close", poll_id=poll_id, automatic=True)
        return closed

    async def delete(self, editor: User, poll_id: int) -> None:
        if not is_moderator(editor):
            raise Forbidden("Only editors can delete polls.")
        poll = await self._get(poll_id)
        await self.db.delete(poll)
        await self.db.commit()
