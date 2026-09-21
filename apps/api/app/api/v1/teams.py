from fastapi import APIRouter, HTTPException

from app.api.deps import FootballServiceDep, PaginationDep
from app.schemas.common import Page
from app.schemas.match import MatchSummary
from app.schemas.team import TeamOut
from app.services.football_service import NotFoundError

router = APIRouter()


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(team_id: int, service: FootballServiceDep) -> TeamOut:
    try:
        return await service.get_team(team_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc


@router.get("/{team_id}/fixtures", response_model=Page[MatchSummary])
async def get_team_fixtures(
    team_id: int, service: FootballServiceDep, pagination: PaginationDep
) -> Page[MatchSummary]:
    page, page_size = pagination
    try:
        items, total = await service.get_team_fixtures(team_id, page, page_size, upcoming_only=True)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{team_id}/results", response_model=Page[MatchSummary])
async def get_team_results(
    team_id: int, service: FootballServiceDep, pagination: PaginationDep
) -> Page[MatchSummary]:
    page, page_size = pagination
    try:
        items, total = await service.get_team_fixtures(team_id, page, page_size, upcoming_only=False)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc
    return Page(items=items, total=total, page=page, page_size=page_size)
