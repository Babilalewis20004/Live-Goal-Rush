from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import RedisService, get_redis_service
from app.db.session import get_db
from app.services.cache import CacheAside
from app.services.football_service import FootballService
from app.services.providers import get_provider
from app.services.providers.base import FootballDataProvider

RedisServiceDep = Annotated[RedisService, Depends(get_redis_service)]


def get_cache(redis: RedisServiceDep) -> CacheAside:
    return CacheAside(redis)


CacheDep = Annotated[CacheAside, Depends(get_cache)]


def get_football_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Annotated[FootballDataProvider, Depends(get_provider)],
    cache: CacheDep,
) -> FootballService:
    return FootballService(db=db, provider=provider, cache=cache)


FootballServiceDep = Annotated[FootballService, Depends(get_football_service)]


def pagination_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> tuple[int, int]:
    return page, page_size


PaginationDep = Annotated[tuple[int, int], Depends(pagination_params)]
