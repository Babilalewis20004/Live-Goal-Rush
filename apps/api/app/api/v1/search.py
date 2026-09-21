from fastapi import APIRouter, Query

from app.api.deps import FootballServiceDep
from app.schemas.search import SearchResults

router = APIRouter()


@router.get("", response_model=SearchResults)
async def search(service: FootballServiceDep, q: str = Query(default="")) -> SearchResults:
    return await service.search(q)
