from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.football_service import FootballService
from app.services.providers import get_provider
from app.services.providers.base import FootballDataProvider


def get_football_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Annotated[FootballDataProvider, Depends(get_provider)],
) -> FootballService:
    return FootballService(db=db, provider=provider)


FootballServiceDep = Annotated[FootballService, Depends(get_football_service)]


def pagination_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> tuple[int, int]:
    return page, page_size


PaginationDep = Annotated[tuple[int, int], Depends(pagination_params)]
