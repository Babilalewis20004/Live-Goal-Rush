"""Unified search, suggestions, popular and recent searches (discovery §19-22).

PostgreSQL does the matching (`FootballService._search_database` for football
entities, `ArticleService.search` for news); this layer groups the results and
owns the search-adjacent state:

* unified results (`/search`) and suggestions -- cached briefly in Redis per normalised query / prefix;
* popular searches -- a per-day Redis sorted set, fed only by *selected*
  results and shown only once several distinct viewers agree;
* recent searches -- signed-in users only, in Postgres, newest 10.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis_client import RedisService
from app.core.redis_keys import RedisKeys
from app.models.competition import Competition
from app.models.engagement import RecentSearch
from app.models.player import Player
from app.models.team import Team
from app.schemas.discovery import SearchSuggestion, SearchSuggestions
from app.schemas.search import SearchResults
from app.services.article_service import ArticleService
from app.services import http_metrics
from app.services.football_service import FootballService
from app.services.search_ranking import matches, normalize_query, similarity, tier

logger = logging.getLogger(__name__)

SUGGESTION_MIN_LENGTH = 2
_SUGGESTION_TTL_SECONDS = 120
_RECENT_LIMIT = 10
_POPULAR_TTL_SECONDS = 3 * 24 * 3600
_MAX_POPULAR_QUERY = 50


def _day(now: datetime) -> str:
    return now.strftime("%Y%m%d")


class SearchService:
    def __init__(
        self, db: AsyncSession, redis: RedisService, football: FootballService, articles: ArticleService
    ) -> None:
        self.db = db
        self.redis = redis
        self.football = football
        self.articles = articles

    async def search(self, query: str, limit: int = 10) -> SearchResults:
        query = normalize_query(query)
        if not query:
            return SearchResults()
        key = RedisKeys.search_results(query.lower()[:60], limit)
        try:
            cached = await self.redis.get(key)
        except Exception:
            cached = None  # Redis down: search still works, just uncached
        if cached is not None:
            http_metrics.SEARCH_REQUESTS.labels("unified_cached").inc()
            return SearchResults.model_validate(cached)

        started = time.perf_counter()
        try:
            results = await self.football.search(query, limit=limit)
            results.articles = await self.articles.search(query, limit=limit)
        finally:
            http_metrics.SEARCH_REQUESTS.labels("unified").inc()
            http_metrics.SEARCH_DURATION.labels("unified").observe(time.perf_counter() - started)
        if not (results.teams or results.competitions or results.players or results.matches or results.articles):
            http_metrics.SEARCH_EMPTY.inc()
        try:
            await self.redis.set(key, results.model_dump(mode="json"), ttl_seconds=settings.search_results_cache_ttl_seconds)
        except Exception:
            logger.warning("Could not cache search results", exc_info=True)
        return results

    # -- suggestions ------------------------------------------------------------

    async def suggestions(self, query: str, limit: int = 8) -> SearchSuggestions:
        query = normalize_query(query)
        if len(query) < SUGGESTION_MIN_LENGTH:
            return SearchSuggestions(query=query)
        http_metrics.SEARCH_REQUESTS.labels("suggestions").inc()
        key = RedisKeys.search_suggestions(query.lower()[:60])
        try:
            cached = await self.redis.get(key)
        except Exception:
            cached = None
        if cached is not None:
            return SearchSuggestions.model_validate(cached)

        suggestions: list[SearchSuggestion] = []
        for model, kind, per_type in ((Team, "team", 3), (Competition, "competition", 2), (Player, "player", 2)):
            rows = await self.db.execute(
                select(model.id, model.name)
                .where(matches(model.name, query))
                .order_by(tier(model.name, query), similarity(model.name, query).desc(), model.name)
                .limit(per_type)
            )
            suggestions += [SearchSuggestion(type=kind, id=i, label=n) for i, n in rows]
        for article_id, slug, title in await self.articles.suggest(query, limit=2):
            suggestions.append(SearchSuggestion(type="article", id=article_id, label=title, slug=slug))

        # Best match quality first overall (exact/prefix suggestions above
        # substring ones), keeping each type's own order.
        def quality(s: SearchSuggestion) -> int:
            label = s.label.lower()
            q = query.lower()
            return 0 if label == q else 1 if label.startswith(q) else 2

        suggestions.sort(key=quality)  # stable
        result = SearchSuggestions(query=query, suggestions=suggestions[:limit])
        try:
            await self.redis.set(key, result.model_dump(mode="json"), ttl_seconds=_SUGGESTION_TTL_SECONDS)
        except Exception:
            logger.warning("Could not cache suggestions", exc_info=True)
        return result

    # -- popular -------------------------------------------------------------------

    async def record_popular(self, query: str, viewer: str) -> None:
        query = normalize_query(query).lower()
        if not (SUGGESTION_MIN_LENGTH <= len(query) <= _MAX_POPULAR_QUERY):
            return
        try:
            raw = self.redis.raw
            # one vote per viewer per query per day
            first = await raw.set(f"football:search:popular-seen:{_day(datetime.now(timezone.utc))}:{viewer}:{query}", "1", nx=True, ex=24 * 3600)
            if not first:
                return
            key = RedisKeys.popular_searches(_day(datetime.now(timezone.utc)))
            await raw.zincrby(key, 1, query)
            await raw.expire(key, _POPULAR_TTL_SECONDS)
        except Exception:
            logger.warning("Could not record popular search", exc_info=True)

    async def popular(self, limit: int = 8) -> list[str]:
        now = datetime.now(timezone.utc)
        totals: dict[str, float] = {}
        try:
            for day in (_day(now), _day(now - timedelta(days=1))):
                for member, score in await self.redis.raw.zrevrange(RedisKeys.popular_searches(day), 0, 49, withscores=True):
                    totals[member] = totals.get(member, 0) + score
        except Exception:
            return []
        eligible = [(q, s) for q, s in totals.items() if s >= settings.popular_search_min_viewers]
        eligible.sort(key=lambda t: (-t[1], t[0]))
        return [q for q, _ in eligible[:limit]]

    # -- recent (signed-in users only) -------------------------------------------------

    async def list_recent(self, user_id: int) -> list[str]:
        rows = await self.db.execute(
            select(RecentSearch.query)
            .where(RecentSearch.user_id == user_id)
            .order_by(RecentSearch.last_searched_at.desc(), RecentSearch.id.desc())
            .limit(_RECENT_LIMIT)
        )
        return [q for (q,) in rows]

    async def add_recent(self, user_id: int, query: str) -> None:
        query = normalize_query(query)
        if len(query) < 2:
            return
        await self.db.execute(
            delete(RecentSearch).where(RecentSearch.user_id == user_id, func.lower(RecentSearch.query) == query.lower())
        )
        await self.db.execute(
            pg_insert(RecentSearch)
            .values(user_id=user_id, query=query)
            .on_conflict_do_update(
                index_elements=["user_id", "query"], set_={"last_searched_at": func.now()}
            )
        )
        keep = select(RecentSearch.id).where(RecentSearch.user_id == user_id).order_by(
            RecentSearch.last_searched_at.desc(), RecentSearch.id.desc()
        ).limit(_RECENT_LIMIT)
        await self.db.execute(
            delete(RecentSearch).where(RecentSearch.user_id == user_id, RecentSearch.id.not_in(keep))
        )
        await self.db.commit()

    async def delete_recent(self, user_id: int, query: str | None) -> None:
        stmt = delete(RecentSearch).where(RecentSearch.user_id == user_id)
        if query is not None:
            stmt = stmt.where(func.lower(RecentSearch.query) == normalize_query(query).lower())
        await self.db.execute(stmt)
        await self.db.commit()
