"""Engagement tracking and trending (discovery §23-27).

Write path (cheap, per request)::

    POST /engagement/view ─► de-dup marker (SET NX EX) ─► HINCRBY hourly counter in Redis

Aggregation (Celery beat, every minute)::

    Redis hourly hashes ─► atomic RENAME ─► upsert engagement_buckets (+ articles.view_count)

Read path (trending)::

    engagement_buckets ─► exponentially-decayed sum per entity ─► Redis cache ─► API

Nothing personal is stored: the de-dup marker holds an HMAC of the client IP
and user agent (keyed with the server secret, so it cannot be reversed to an
address) for `view_dedup_seconds` and then expires; the durable table only
holds counts per entity per hour.

Delivery of counts is *at-least-once*: if the process dies between committing
a batch and deleting its Redis hash, that batch is counted again on the next
run. For popularity ranking that is an acceptable trade for not needing a
distributed transaction; it is documented rather than hidden.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis_keys import RedisKeys
from app.models.article import Article, article_competitions, article_players, article_teams
from app.models.article import ArticleCategory
from app.models.engagement import EngagementBucket
from app.models.enums import ArticleStatus, EngagementEntity, EngagementSignal, MatchStatus
from app.models.favourite import FavouriteCompetition, FavouriteTeam
from app.models.competition import Competition
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team

logger = logging.getLogger(__name__)

_COUNTER_TTL_SECONDS = 3 * 24 * 3600
_SEARCH_DEDUP_SECONDS = 600
_RETENTION_DAYS = 30

# A deliberate search-result selection says more than a page view does.
SIGNAL_WEIGHTS = {EngagementSignal.VIEW.value: 1.0, EngagementSignal.SEARCH.value: 3.0}
_LIVE_MATCH_BONUS = 5.0
_FOLLOW_BONUS = 2.0
_NEWS_BONUS = 2.0
_PLAYER_NEWS_BONUS = 3.0
_MATCH_VIEW_WEIGHT = 0.5  # a match view lends half a view to each team
_ARTICLE_HALF_LIFE_HOURS = 48.0


def viewer_fingerprint(ip: str | None, user_agent: str | None) -> str:
    digest = hmac.new(
        settings.jwt_secret.encode(), f"{ip or ''}|{user_agent or ''}".encode(), hashlib.sha256
    ).hexdigest()
    return digest[:20]


_ENTITY_MODELS = {
    EngagementEntity.ARTICLE.value: Article,
    EngagementEntity.TEAM.value: Team,
    EngagementEntity.PLAYER.value: Player,
    EngagementEntity.COMPETITION.value: Competition,
    EngagementEntity.MATCH.value: Match,
}


async def entity_exists(db: AsyncSession, entity_type: EngagementEntity | str, entity_id: int) -> bool:
    """Only real, public things may be counted -- otherwise anyone could pad
    the counters with made-up ids. Articles must be published."""
    entity = EngagementEntity(entity_type).value
    model = _ENTITY_MODELS[entity]
    stmt = select(model.id).where(model.id == entity_id)
    if entity == EngagementEntity.ARTICLE.value:
        stmt = stmt.where(Article.status == ArticleStatus.PUBLISHED, Article.published_at <= func.now())
    return (await db.scalar(stmt)) is not None


def _bucket_epoch(now: datetime) -> int:
    return int(now.replace(minute=0, second=0, microsecond=0).timestamp())


async def record_engagement(
    redis: Redis,
    entity_type: EngagementEntity | str,
    entity_id: int,
    signal: EngagementSignal | str,
    viewer: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Count one view/search for an entity, unless this viewer already counted
    for it recently. Returns True when it was counted. Fails open: an
    unreachable Redis means the interaction is simply not counted."""
    entity = EngagementEntity(entity_type).value
    sig = EngagementSignal(signal).value
    now = now or datetime.now(timezone.utc)
    window = settings.view_dedup_seconds if sig == EngagementSignal.VIEW.value else _SEARCH_DEDUP_SECONDS
    try:
        first = await redis.set(RedisKeys.engagement_seen(sig, entity, entity_id, viewer), "1", nx=True, ex=window)
        if not first:
            return False
        key = RedisKeys.engagement_counts(_bucket_epoch(now))
        await redis.hincrby(key, f"{entity}:{entity_id}:{sig}", 1)
        await redis.expire(key, _COUNTER_TTL_SECONDS)
        return True
    except Exception:
        logger.warning("Engagement tracking skipped (Redis unavailable)", exc_info=True)
        return False


def _parse_fields(data: dict[str, str]) -> list[tuple[str, int, str, int]]:
    rows: list[tuple[str, int, str, int]] = []
    valid_entities = {e.value for e in EngagementEntity}
    valid_signals = {s.value for s in EngagementSignal}
    for field_name, raw_count in data.items():
        parts = field_name.split(":")
        if len(parts) != 3 or parts[0] not in valid_entities or parts[2] not in valid_signals:
            continue
        try:
            entity_id, count = int(parts[1]), int(raw_count)
        except ValueError:
            continue
        if entity_id > 0 and count > 0:
            rows.append((parts[0], entity_id, parts[2], count))
    return rows


async def aggregate_engagement(redis: Redis, db: AsyncSession) -> int:
    """Move Redis hourly counters into `engagement_buckets` (and advance
    `articles.view_count`). Returns the number of (entity, signal, hour) rows
    written. Safe to run concurrently with request traffic and with itself:
    RENAME is atomic, so each counter batch is claimed by exactly one run."""
    written = 0
    count_keys = [k async for k in redis.scan_iter(match=f"{RedisKeys.ENGAGEMENT_COUNTS_PREFIX}*", count=200)]
    # Batches an earlier run claimed but never finished (crashed mid-way).
    flush_keys = [k async for k in redis.scan_iter(match=f"{RedisKeys.ENGAGEMENT_FLUSH_PREFIX}*", count=200)]

    pending: list[tuple[str, int, str]] = []  # (flush_key, bucket_epoch, original_counts_key)
    for key in count_keys:
        bucket = int(key.rsplit(":", 1)[1])
        flush_key = f"{RedisKeys.ENGAGEMENT_FLUSH_PREFIX}{bucket}:{uuid.uuid4().hex}"
        try:
            await redis.rename(key, flush_key)
        except ResponseError:
            continue  # another run took it between SCAN and RENAME
        await redis.expire(flush_key, 24 * 3600)
        pending.append((flush_key, bucket, key))
    for flush_key in flush_keys:
        bucket = int(flush_key[len(RedisKeys.ENGAGEMENT_FLUSH_PREFIX) :].split(":")[0])
        pending.append((flush_key, bucket, RedisKeys.engagement_counts(bucket)))

    for flush_key, bucket_epoch, original_key in pending:
        data = await redis.hgetall(flush_key)
        rows = _parse_fields(data)
        if not rows:
            await redis.delete(flush_key)
            continue
        bucket = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)
        try:
            stmt = pg_insert(EngagementBucket).values(
                [
                    {"entity_type": t, "entity_id": i, "signal": s, "bucket": bucket, "count": c}
                    for t, i, s, c in rows
                ]
            )
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["entity_type", "entity_id", "signal", "bucket"],
                    set_={"count": EngagementBucket.count + stmt.excluded.count},
                )
            )
            article_views = [(i, c) for t, i, s, c in rows if t == "article" and s == "view"]
            for article_id, views in article_views:
                await db.execute(
                    update(Article).where(Article.id == article_id).values(view_count=Article.view_count + views)
                )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Engagement aggregation failed for %s; returning its counts to Redis", flush_key)
            for field_name, raw in data.items():
                await redis.hincrby(original_key, field_name, int(raw))
            await redis.delete(flush_key)
            continue
        await redis.delete(flush_key)
        written += len(rows)

    await db.execute(
        delete(EngagementBucket).where(EngagementBucket.bucket < datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS))
    )
    await db.commit()
    return written


# -- trending ----------------------------------------------------------------


@dataclass
class TrendScore:
    id: int
    score: float = 0.0
    signals: dict[str, int] = field(default_factory=dict)

    def add(self, name: str, count: float, weight: float, *, decayed: float | None = None) -> None:
        if count <= 0:
            return
        self.signals[name] = self.signals.get(name, 0) + int(round(count))
        self.score += weight * (decayed if decayed is not None else count)


def _decay_expression(half_life_hours: float):
    age_hours = func.greatest(func.extract("epoch", func.now() - EngagementBucket.bucket) / 3600.0, 0.0)
    return func.exp(-math.log(2) * age_hours / half_life_hours)


async def _engagement_scores(
    db: AsyncSession, entity_type: str, window_hours: int, scores: dict[int, TrendScore], *, weight_scale: float = 1.0
) -> None:
    decay = _decay_expression(settings.trending_half_life_hours)
    rows = await db.execute(
        select(
            EngagementBucket.entity_id,
            EngagementBucket.signal,
            func.sum(EngagementBucket.count * decay),
            func.sum(EngagementBucket.count),
        )
        .where(
            EngagementBucket.entity_type == entity_type,
            EngagementBucket.bucket >= func.now() - timedelta(hours=window_hours),
        )
        .group_by(EngagementBucket.entity_id, EngagementBucket.signal)
    )
    for entity_id, signal, decayed, raw in rows:
        name = "views" if signal == EngagementSignal.VIEW.value else "searches"
        scores.setdefault(entity_id, TrendScore(entity_id)).add(
            name, float(raw), SIGNAL_WEIGHTS[signal] * weight_scale, decayed=float(decayed)
        )


async def _live_team_counts(db: AsyncSession) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    rows = await db.execute(
        select(Match.home_team_id, Match.away_team_id).where(
            Match.status.in_([MatchStatus.LIVE, MatchStatus.HALFTIME])
        )
    )
    for home, away in rows:
        counts[home] += 1
        counts[away] += 1
    return counts


def _published_in_window(window_hours: int):
    return (
        Article.status == ArticleStatus.PUBLISHED,
        Article.published_at >= func.now() - timedelta(hours=window_hours),
        Article.published_at <= func.now(),
    )


async def compute_trending(
    db: AsyncSession, entity_type: EngagementEntity | str, window_hours: int | None = None, limit: int = 30
) -> list[TrendScore]:
    """Deterministic, explainable popularity. Every contribution is a counted
    thing (views, searches, live matches, follows, news) with a fixed weight;
    entities with no contribution are *not* ranked at all."""
    entity = EngagementEntity(entity_type).value
    window = window_hours or settings.trending_window_hours
    scores: dict[int, TrendScore] = {}

    if entity == "match":
        raise ValueError("matches are not ranked; their views are attributed to teams")

    await _engagement_scores(db, entity, window, scores)

    if entity == "team":
        # Match views lend attention to both teams, discounted.
        match_scores: dict[int, TrendScore] = {}
        await _engagement_scores(db, "match", window, match_scores)
        top_matches = sorted(match_scores.values(), key=lambda s: -s.score)[:200]
        if top_matches:
            by_id = {s.id: s for s in top_matches}
            for match_id, home, away in await db.execute(
                select(Match.id, Match.home_team_id, Match.away_team_id).where(Match.id.in_(by_id))
            ):
                for team_id in (home, away):
                    scores.setdefault(team_id, TrendScore(team_id)).add(
                        "match_views", by_id[match_id].signals.get("views", 0), _MATCH_VIEW_WEIGHT,
                        decayed=by_id[match_id].score,
                    )
        for team_id, live in (await _live_team_counts(db)).items():
            scores.setdefault(team_id, TrendScore(team_id)).add("live_matches", live, _LIVE_MATCH_BONUS)
        for team_id, follows in await db.execute(
            select(FavouriteTeam.team_id, func.count())
            .where(FavouriteTeam.created_at >= func.now() - timedelta(hours=window))
            .group_by(FavouriteTeam.team_id)
        ):
            scores.setdefault(team_id, TrendScore(team_id)).add("follows", follows, _FOLLOW_BONUS)
        for team_id, news in await db.execute(
            select(article_teams.c.team_id, func.count())
            .join(Article, Article.id == article_teams.c.article_id)
            .where(*_published_in_window(window))
            .group_by(article_teams.c.team_id)
        ):
            scores.setdefault(team_id, TrendScore(team_id)).add("news", news, _NEWS_BONUS)

    elif entity == "player":
        for player_id, news in await db.execute(
            select(article_players.c.player_id, func.count())
            .join(Article, Article.id == article_players.c.article_id)
            .where(*_published_in_window(window))
            .group_by(article_players.c.player_id)
        ):
            scores.setdefault(player_id, TrendScore(player_id)).add("news", news, _PLAYER_NEWS_BONUS)

    elif entity == "competition":
        live_by_competition = await db.execute(
            select(Match.competition_id, func.count())
            .where(Match.status.in_([MatchStatus.LIVE, MatchStatus.HALFTIME]))
            .group_by(Match.competition_id)
        )
        for competition_id, live in live_by_competition:
            scores.setdefault(competition_id, TrendScore(competition_id)).add("live_matches", live, _LIVE_MATCH_BONUS)
        for competition_id, follows in await db.execute(
            select(FavouriteCompetition.competition_id, func.count())
            .where(FavouriteCompetition.created_at >= func.now() - timedelta(hours=window))
            .group_by(FavouriteCompetition.competition_id)
        ):
            scores.setdefault(competition_id, TrendScore(competition_id)).add("follows", follows, _FOLLOW_BONUS)
        for competition_id, news in await db.execute(
            select(article_competitions.c.competition_id, func.count())
            .join(Article, Article.id == article_competitions.c.article_id)
            .where(*_published_in_window(window))
            .group_by(article_competitions.c.competition_id)
        ):
            scores.setdefault(competition_id, TrendScore(competition_id)).add("news", news, _NEWS_BONUS)
        for competition_id, news in await db.execute(
            select(ArticleCategory.competition_id, func.count())
            .join(Article, Article.category_id == ArticleCategory.id)
            .where(ArticleCategory.competition_id.is_not(None), *_published_in_window(window))
            .group_by(ArticleCategory.competition_id)
        ):
            scores.setdefault(competition_id, TrendScore(competition_id)).add("news", news, _NEWS_BONUS)

    elif entity == "article":
        # Views only, but old articles must not stay trending forever: apply a
        # second, slower decay on the article's age.
        if scores:
            published = {
                article_id: published_at
                for article_id, published_at in await db.execute(
                    select(Article.id, Article.published_at).where(
                        Article.id.in_(scores), Article.status == ArticleStatus.PUBLISHED
                    )
                )
            }
            now = datetime.now(timezone.utc)
            for article_id in list(scores):
                if article_id not in published or published[article_id] is None:
                    del scores[article_id]
                    continue
                age_hours = max((now - published[article_id]).total_seconds() / 3600.0, 0.0)
                scores[article_id].score *= math.exp(-math.log(2) * age_hours / _ARTICLE_HALF_LIFE_HOURS)

    ranked = [s for s in scores.values() if s.score > 0]
    ranked.sort(key=lambda s: (-s.score, s.id))
    return ranked[:limit]
