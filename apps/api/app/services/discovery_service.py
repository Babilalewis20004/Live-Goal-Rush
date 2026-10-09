"""Discovery: trending, the home payload and the personalised feed
(discovery §5-7, §23-26, §29).

Everything here is deterministic and explainable. The feed is a fixed list of
*tiers* (below); each item carries the tier it came from and a sentence saying
why it is there. Nothing is learned, and nothing is invented: a section with
no data is empty.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis_client import RedisService
from app.core.redis_keys import RedisKeys
from app.models.article import Article, article_competitions, article_teams
from app.models.community import Comment, Poll, PollVote, Reaction
from app.models.competition import Competition
from app.models.engagement import RecentSearch
from app.models.enums import ArticleStatus, CommentStatus, EngagementEntity, MatchStatus
from app.models.favourite import FavouriteCompetition, FavouriteMatch, FavouriteTeam
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.user import User
from app.schemas.article import ArticleSummary
from app.schemas.competition import CompetitionOut
from app.schemas.discovery import DiscoveryHome, FeedItem, FeedOut, Trending, TrendingOut
from app.schemas.match import MatchSummary
from app.schemas.player import PlayerOut
from app.schemas.team import TeamOut
from app.services.article_service import ArticleService
from app.services.cache import CacheAside
from app.services.engagement_service import TrendScore, compute_trending
from app.services.football_service import _MATCH_LOAD_OPTIONS

logger = logging.getLogger(__name__)

TRENDING_TYPES = ("team", "player", "competition", "article")
_LIVE = (MatchStatus.LIVE, MatchStatus.HALFTIME)
_FEED_LIMIT = 30

# The feed's priority order. Lower rank = shown first. Documented in
# docs/architecture/discovery.md; keep in sync.
FEED_TIERS = {
    "live_followed_match": 1,
    "followed_team_today": 2,
    "followed_competition_today": 3,
    "followed_team_upcoming": 4,
    "followed_competition_upcoming": 4,
    "recent_result": 5,
    "news_followed_team": 6,
    "news_followed_competition": 6,
    "news_searched": 7,
    "community_match": 4,
    "community_article": 7,
    "trending": 8,
    "latest": 9,
}


def _day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


class DiscoveryService:
    def __init__(self, db: AsyncSession, redis: RedisService, articles: ArticleService) -> None:
        self.db = db
        self.redis = redis
        self.articles = articles
        self.cache = CacheAside(redis)

    # -- trending -------------------------------------------------------------

    async def _scores(self, entity: str, window: int) -> list[TrendScore]:
        key = RedisKeys.trending(entity, window)
        try:
            cached = await self.redis.get(key)
        except Exception:
            cached = None
        if cached is not None:
            return [TrendScore(id=r["id"], score=r["score"], signals=r["signals"]) for r in cached]
        scores = await compute_trending(self.db, entity, window)
        await store_trending(self.redis, entity, window, scores)
        return scores

    async def _hydrate(self, entity: str, scores: list[TrendScore], limit: int) -> list[Trending[Any]]:
        ids = [s.id for s in scores]
        if not ids:
            return []
        by_score = {s.id: s for s in scores}
        if entity == "team":
            rows = {r.id: TeamOut.model_validate(r) for r in (await self.db.execute(select(Team).where(Team.id.in_(ids)))).scalars()}
        elif entity == "player":
            rows = {r.id: PlayerOut.model_validate(r) for r in (await self.db.execute(select(Player).where(Player.id.in_(ids)))).scalars()}
        elif entity == "competition":
            rows = {
                r.id: CompetitionOut.model_validate(r)
                for r in (await self.db.execute(select(Competition).where(Competition.id.in_(ids)))).scalars()
            }
        else:
            rows = {a.id: a for a in await self.articles.by_ids(ids)}
        out = [
            Trending(item=rows[i], score=round(by_score[i].score, 3), signals=by_score[i].signals)
            for i in ids
            if i in rows
        ]
        return out[:limit]

    async def trending(self, entity: str, *, window: int | None = None, limit: int = 10) -> list[Trending[Any]]:
        window = window or settings.trending_window_hours
        scores = await self._scores(entity, window)
        return await self._hydrate(entity, scores[: limit * 2], limit)

    async def trending_all(self, *, window: int | None = None, limit: int = 10) -> TrendingOut:
        window = window or settings.trending_window_hours
        return TrendingOut(
            window_hours=window,
            teams=await self.trending("team", window=window, limit=limit),
            players=await self.trending("player", window=window, limit=limit),
            competitions=await self.trending("competition", window=window, limit=limit),
            articles=await self.trending("article", window=window, limit=limit),
        )

    # -- home -------------------------------------------------------------------

    async def home(self) -> DiscoveryHome:
        version = await self.articles._version()
        return await self.cache.get_or_set_model(
            RedisKeys.discovery_home(version), DiscoveryHome, self._build_home, ttl_seconds=settings.discovery_cache_ttl_seconds
        )

    async def _build_home(self) -> DiscoveryHome:
        results = (
            (
                await self.db.execute(
                    select(Match)
                    .where(Match.status == MatchStatus.FINISHED)
                    .order_by(Match.kickoff_time.desc())
                    .limit(8)
                    .options(*_MATCH_LOAD_OPTIONS)
                )
            )
            .scalars()
            .all()
        )
        trending_competitions = await self.trending("competition", limit=8)
        if trending_competitions:
            popular = [t.item for t in trending_competitions]
        else:
            # No engagement data yet: fall back to the busiest competitions by
            # fixtures in the coming week -- real activity, not a made-up ranking.
            now = datetime.now(timezone.utc)
            rows = await self.db.execute(
                select(Competition)
                .join(Match, Match.competition_id == Competition.id)
                .where(Match.kickoff_time >= now - timedelta(days=1), Match.kickoff_time < now + timedelta(days=7))
                .group_by(Competition.id)
                .order_by(func.count().desc(), Competition.name)
                .limit(8)
            )
            popular = [CompetitionOut.model_validate(c) for c in rows.scalars()]
        return DiscoveryHome(
            latest_results=[MatchSummary.model_validate(m) for m in results],
            featured_articles=await self.articles.latest(3, featured=True),
            latest_articles=await self.articles.latest(6),
            trending_teams=await self.trending("team", limit=6),
            trending_players=await self.trending("player", limit=6),
            trending_articles=await self.trending("article", limit=5),
            popular_competitions=popular,
            generated_at=datetime.now(timezone.utc),
        )

    # -- personalised feed ----------------------------------------------------------

    async def feed(self, user: User) -> FeedOut:
        key = RedisKeys.user_feed(user.id)  # per-user key: never served to anyone else
        return await self.cache.get_or_set_model(
            key, FeedOut, lambda: self._build_feed(user), ttl_seconds=settings.feed_cache_ttl_seconds
        )

    async def _build_feed(self, user: User) -> FeedOut:
        team_rows = (await self.db.execute(
            select(Team.id, Team.name).join(FavouriteTeam, FavouriteTeam.team_id == Team.id).where(FavouriteTeam.user_id == user.id)
        )).all()
        competition_rows = (await self.db.execute(
            select(Competition.id, Competition.name)
            .join(FavouriteCompetition, FavouriteCompetition.competition_id == Competition.id)
            .where(FavouriteCompetition.user_id == user.id)
        )).all()
        match_ids = [m for (m,) in (await self.db.execute(select(FavouriteMatch.match_id).where(FavouriteMatch.user_id == user.id))).all()]
        teams = {i: n for i, n in team_rows}
        competitions = {i: n for i, n in competition_rows}

        searched_teams: dict[int, str] = {}
        recent = [q for (q,) in (await self.db.execute(
            select(RecentSearch.query).where(RecentSearch.user_id == user.id).order_by(RecentSearch.last_searched_at.desc()).limit(10)
        )).all()]
        if recent:
            lowered = [q.lower() for q in recent]
            for team_id, name in await self.db.execute(select(Team.id, Team.name).where(func.lower(Team.name).in_(lowered))):
                if team_id not in teams:
                    searched_teams[team_id] = name

        community_articles, community_matches = await self._community_targets(user.id)
        if not (teams or competitions or match_ids or community_articles or community_matches):
            return FeedOut(items=await self._general_items(), personalised=False)

        now = datetime.now(timezone.utc)
        day_start, day_end = _day_bounds(now)
        involved = or_(
            Match.id.in_(match_ids) if match_ids else False,
            Match.home_team_id.in_(list(teams)) if teams else False,
            Match.away_team_id.in_(list(teams)) if teams else False,
            Match.competition_id.in_(list(competitions)) if competitions else False,
        )

        items: dict[tuple[str, int], FeedItem] = {}

        def put(kind: str, ident: int, item: FeedItem) -> None:
            existing = items.get((kind, ident))
            if existing is None or item.rank < existing.rank:
                items[(kind, ident)] = item

        def followed_team_name(m: Match) -> str | None:
            for team in (m.home_team, m.away_team):
                if team.id in teams:
                    return team.name
            return None

        matches = list(
            (
                await self.db.execute(
                    select(Match)
                    .where(
                        involved,
                        or_(
                            Match.status.in_(_LIVE),
                            Match.kickoff_time.between(now - timedelta(days=3), now + timedelta(days=7)),
                        ),
                    )
                    .order_by(Match.kickoff_time)
                    .limit(200)
                    .options(*_MATCH_LOAD_OPTIONS)
                )
            ).scalars()
        )
        match_ids_set = set(match_ids)
        for m in matches:
            summary = MatchSummary.model_validate(m)
            by_team = followed_team_name(m)
            by_match = m.id in match_ids_set
            by_competition = m.competition_id in competitions
            fixture = f"{m.home_team.name} v {m.away_team.name}"
            if m.status in _LIVE:
                why = f"{fixture} is live now" + ("" if by_match else f" ({by_team or competitions[m.competition_id]})")
                reason = "live_followed_match"
            elif m.status == MatchStatus.FINISHED:
                if m.kickoff_time < now - timedelta(days=3):
                    continue
                reason, why = "recent_result", f"Result: {fixture}"
            elif day_start <= m.kickoff_time < day_end and (by_team or by_match):
                reason = "followed_team_today"
                why = f"{by_team} is playing today" if by_team else f"Today: {fixture} (a match you follow)"
            elif day_start <= m.kickoff_time < day_end:
                reason, why = "followed_competition_today", f"{competitions[m.competition_id]} today: {fixture}"
            elif m.kickoff_time >= day_end and (by_team or by_match):
                reason = "followed_team_upcoming"
                why = f"Next for {by_team}: {fixture}" if by_team else f"Upcoming: {fixture} (a match you follow)"
            elif m.kickoff_time >= day_end and by_competition and m.kickoff_time < day_end + timedelta(days=3):
                reason, why = "followed_competition_upcoming", f"Coming up in {competitions[m.competition_id]}: {fixture}"
            else:
                continue
            put("match", m.id, FeedItem(kind="match", reason=reason, explanation=why, rank=FEED_TIERS[reason], match=summary))

        # News linked to followed teams / competitions (last 7 days).
        recent_cut = now - timedelta(days=7)
        news_clauses = []
        if teams:
            news_clauses.append(self.articles._has_team(list(teams)))
        for cid in competitions:
            news_clauses.append(self.articles._has_competition(cid))
        if news_clauses:
            article_rows = (
                await self.db.execute(
                    select(Article.id)
                    .where(self.articles._public(), Article.published_at >= recent_cut, or_(*news_clauses))
                    .order_by(Article.published_at.desc())
                    .limit(10)
                )
            ).scalars().all()
            linked_teams = await self.articles._link_ids(article_teams, "team_id", list(article_rows)) if article_rows else {}
            linked_comps = await self.articles._link_ids(article_competitions, "competition_id", list(article_rows)) if article_rows else {}
            for summary in await self.articles.by_ids(list(article_rows)):
                team_hit = next((teams[t] for t in linked_teams.get(summary.id, set()) if t in teams), None)
                if team_hit:
                    reason, why = "news_followed_team", f"News about {team_hit}"
                else:
                    comp_hit = next((competitions[c] for c in linked_comps.get(summary.id, set()) if c in competitions), None)
                    if comp_hit is None and summary.category and summary.category.competition_id in competitions:
                        comp_hit = competitions[summary.category.competition_id]
                    reason, why = "news_followed_competition", f"News from {comp_hit or 'a competition you follow'}"
                put("article", summary.id, FeedItem(kind="article", reason=reason, explanation=why, rank=FEED_TIERS[reason], article=summary))

        if searched_teams:
            searched_ids = (
                await self.db.execute(
                    select(Article.id)
                    .where(self.articles._public(), Article.published_at >= recent_cut, self.articles._has_team(list(searched_teams)))
                    .order_by(Article.published_at.desc())
                    .limit(3)
                )
            ).scalars().all()
            for summary in await self.articles.by_ids(list(searched_ids)):
                put("article", summary.id, FeedItem(kind="article", reason="news_searched", explanation="Because you searched for this recently", rank=FEED_TIERS["news_searched"], article=summary))

        # Community signals (deterministic, explainable): things you commented on, reacted to or
        # voted in during the last 14 days. Never beats a live followed match or today's game.
        if community_matches:
            for m in (
                await self.db.execute(
                    select(Match)
                    .where(
                        Match.id.in_(community_matches),
                        or_(Match.status.in_(_LIVE), Match.kickoff_time.between(now - timedelta(days=1), now + timedelta(days=7))),
                    )
                    .options(*_MATCH_LOAD_OPTIONS)
                )
            ).scalars():
                fixture = f"{m.home_team.name} v {m.away_team.name}"
                put("match", m.id, FeedItem(kind="match", reason="community_match", explanation=f"You joined the conversation on {fixture}", rank=FEED_TIERS["community_match"], match=MatchSummary.model_validate(m)))
        if community_articles:
            public_ids = (
                await self.db.execute(
                    select(Article.id).where(self.articles._public(), Article.id.in_(community_articles)).order_by(Article.published_at.desc()).limit(3)
                )
            ).scalars().all()
            for summary in await self.articles.by_ids(list(public_ids)):
                put("article", summary.id, FeedItem(kind="article", reason="community_article", explanation="You commented, reacted or voted here recently", rank=FEED_TIERS["community_article"], article=summary))

        for trend in await self.trending("article", limit=3):
            put("article", trend.item.id, FeedItem(kind="article", reason="trending", explanation="Trending in football", rank=FEED_TIERS["trending"], article=trend.item))

        ordered = sorted(
            items.values(),
            key=lambda i: (
                i.rank,
                # live: most recently kicked off first; fixtures: soonest first;
                # results/news: newest first.
                (-(i.match.kickoff_time.timestamp()) if i.reason in ("live_followed_match", "recent_result") else i.match.kickoff_time.timestamp())
                if i.match
                else -(i.article.published_at.timestamp() if i.article and i.article.published_at else 0),
            ),
        )
        return FeedOut(items=ordered[:_FEED_LIMIT], personalised=True)

    async def _community_targets(self, user_id: int) -> tuple[set[int], set[int]]:
        """(article ids, match ids) the user commented on, reacted to or voted in over the last 14 days."""
        since = datetime.now(timezone.utc) - timedelta(days=14)
        articles: set[int] = set()
        matches: set[int] = set()
        comment_rows = await self.db.execute(
            select(Comment.target_type, Comment.target_id).where(
                Comment.user_id == user_id, Comment.status == CommentStatus.VISIBLE, Comment.created_at >= since
            )
        )
        reaction_rows = await self.db.execute(
            select(Reaction.target_type, Reaction.target_id).where(Reaction.user_id == user_id, Reaction.created_at >= since)
        )
        for target_type, target_id in [*comment_rows.all(), *reaction_rows.all()]:
            (articles if target_type.value == "article" else matches).add(target_id)
        poll_rows = await self.db.execute(
            select(Poll.article_id, Poll.match_id)
            .join(PollVote, PollVote.poll_id == Poll.id)
            .where(PollVote.user_id == user_id, PollVote.created_at >= since)
        )
        for article_id, match_id in poll_rows.all():
            if article_id:
                articles.add(article_id)
            if match_id:
                matches.add(match_id)
        return articles, matches

    async def _general_items(self) -> list[FeedItem]:
        """Feed for a user who follows nothing yet (or an anonymous visitor's
        equivalent): what is trending, then the latest news."""
        items: list[FeedItem] = []
        seen: set[int] = set()
        for trend in await self.trending("article", limit=5):
            seen.add(trend.item.id)
            items.append(FeedItem(kind="article", reason="trending", explanation="Trending in football", rank=FEED_TIERS["trending"], article=trend.item))
        for article in await self.articles.latest(8):
            if article.id not in seen:
                items.append(FeedItem(kind="article", reason="latest", explanation="Latest football news", rank=FEED_TIERS["latest"], article=article))
        return items[:10]


async def store_trending(redis: RedisService, entity: str, window: int, scores: list[TrendScore]) -> None:
    try:
        await redis.set(
            RedisKeys.trending(entity, window),
            [{"id": s.id, "score": s.score, "signals": s.signals} for s in scores],
            ttl_seconds=settings.trending_cache_ttl_seconds,
        )
    except Exception:
        logger.warning("Could not cache trending %s", entity, exc_info=True)


async def refresh_trending(db: AsyncSession, redis: RedisService, window: int | None = None) -> dict[str, int]:
    """Recompute and cache every trending list (the beat task's body)."""
    window = window or settings.trending_window_hours
    counts: dict[str, int] = {}
    for entity in TRENDING_TYPES:
        scores = await compute_trending(db, EngagementEntity(entity), window)
        await store_trending(redis, entity, window, scores)
        counts[entity] = len(scores)
    return counts
