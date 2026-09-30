from fastapi import APIRouter, HTTPException

from app.api.deps import TeamPlayerServiceDep
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
