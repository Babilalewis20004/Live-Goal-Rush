"""Discovery API: the public home payload, trending, and the signed-in feed."""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUserDep, DiscoveryServiceDep
from app.schemas.discovery import DiscoveryHome, FeedOut, Trending, TrendingOut

router = APIRouter()
feed_router = APIRouter()

_ENTITIES = {"teams": "team", "players": "player", "competitions": "competition", "articles": "article"}


@router.get("/home", response_model=DiscoveryHome)
async def discovery_home(service: DiscoveryServiceDep) -> DiscoveryHome:
    """Public and cacheable -- identical for every visitor."""
    return await service.home()


@router.get("/trending", response_model=TrendingOut)
async def trending(
    service: DiscoveryServiceDep,
    window_hours: Annotated[int, Query(ge=1, le=168)] = 24,
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
) -> TrendingOut:
    return await service.trending_all(window=window_hours, limit=limit)


@router.get("/trending/{entity}", response_model=list[Trending[Any]])
async def trending_entity(
    entity: str,
    service: DiscoveryServiceDep,
    window_hours: Annotated[int, Query(ge=1, le=168)] = 24,
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
) -> list[Trending[Any]]:
    kind = _ENTITIES.get(entity)
    if kind is None:
        raise HTTPException(status_code=404, detail="Unknown trending type")
    return await service.trending(kind, window=window_hours, limit=limit)


@feed_router.get("", response_model=FeedOut)
async def my_feed(user: CurrentUserDep, service: DiscoveryServiceDep) -> FeedOut:
    """The caller's own feed. Authenticated only, never cached across users,
    and never exposed to anyone else."""
    return await service.feed(user)
