from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, OptionalUserDep, RedisServiceDep, SearchServiceDep
from app.core.config import settings
from app.core.rate_limit import client_ip, rate_limiter
from app.db.session import get_db
from app.models.enums import EngagementSignal
from app.schemas.discovery import PopularSearches, RecentSearchesOut, SearchSuggestions, SearchTrackIn
from app.schemas.search import SearchResults
from app.services.engagement_service import entity_exists, record_engagement, viewer_fingerprint
from app.services.search_ranking import MAX_QUERY_LENGTH

router = APIRouter()

_search_limit = Depends(rate_limiter("search", settings.search_rate_limit_per_minute, 60))
_track_limit = Depends(rate_limiter("track", settings.track_rate_limit_per_minute, 60))


@router.get("", response_model=SearchResults, dependencies=[_search_limit])
async def search(
    service: SearchServiceDep,
    q: Annotated[str, Query(max_length=MAX_QUERY_LENGTH)] = "",
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> SearchResults:
    """Grouped results across teams, competitions, players, matches and news,
    each group ordered exact > prefix > contains > fuzzy."""
    return await service.search(q, limit=limit)


@router.get("/suggestions", response_model=SearchSuggestions, dependencies=[_search_limit])
async def suggestions(
    service: SearchServiceDep, q: Annotated[str, Query(max_length=MAX_QUERY_LENGTH)] = ""
) -> SearchSuggestions:
    return await service.suggestions(q)


@router.get("/popular", response_model=PopularSearches)
async def popular(service: SearchServiceDep) -> PopularSearches:
    return PopularSearches(queries=await service.popular())


@router.get("/recent", response_model=RecentSearchesOut)
async def recent(user: CurrentUserDep, service: SearchServiceDep) -> RecentSearchesOut:
    """The caller's own recent searches -- never anyone else's."""
    return RecentSearchesOut(queries=await service.list_recent(user.id))


@router.delete("/recent", status_code=status.HTTP_204_NO_CONTENT)
async def clear_recent(
    user: CurrentUserDep,
    service: SearchServiceDep,
    query: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
) -> None:
    """Forget one search (`?query=`) or all of them."""
    await service.delete_recent(user.id, query)


@router.post("/track", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_track_limit])
async def track_search(
    payload: SearchTrackIn,
    request: Request,
    service: SearchServiceDep,
    redis: RedisServiceDep,
    user: OptionalUserDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """A search was submitted or a result was chosen. Signed-in users get it
    added to their recent searches; choosing a result also counts as a search
    signal for that entity (trending) and as a vote for the query being
    popular. Anonymous callers contribute only to the anonymous aggregates."""
    viewer = viewer_fingerprint(client_ip(request), request.headers.get("user-agent"))
    if user is not None:
        await service.add_recent(user.id, payload.query)
    if payload.entity_type is not None and payload.entity_id is not None:
        if await entity_exists(db, payload.entity_type, payload.entity_id):
            await record_engagement(redis.raw, payload.entity_type, payload.entity_id, EngagementSignal.SEARCH, viewer)
            await service.record_popular(payload.query, viewer)

