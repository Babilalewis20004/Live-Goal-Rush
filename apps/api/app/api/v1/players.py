from fastapi import APIRouter, HTTPException

from app.api.deps import ArticleServiceDep, PaginationDep, TeamPlayerServiceDep
from app.schemas.article import ArticleSummary
from app.schemas.common import Page
from app.schemas.player import PlayerDetail
from app.schemas.statistics import PlayerStatisticsOut
from app.services.football_service import NotFoundError

router = APIRouter()


@router.get("/{player_id}", response_model=PlayerDetail)
async def get_player(player_id: int, service: TeamPlayerServiceDep) -> PlayerDetail:
    try:
        return await service.get_player(player_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Player not found") from exc


@router.get("/{player_id}/statistics", response_model=PlayerStatisticsOut)
async def get_player_statistics(player_id: int, service: TeamPlayerServiceDep) -> PlayerStatisticsOut:
    try:
        return await service.get_player_statistics(player_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Player not found") from exc


@router.get("/{player_id}/news", response_model=Page[ArticleSummary])
async def get_player_news(player_id: int, articles: ArticleServiceDep, pagination: PaginationDep) -> Page[ArticleSummary]:
    """Published articles explicitly linked to this player."""
    page, page_size = pagination
    try:
        return await articles.list_for_player(player_id, page, page_size)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Player not found") from exc
