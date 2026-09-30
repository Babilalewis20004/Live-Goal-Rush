from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.deps import FootballServiceDep, FormServiceDep, PaginationDep, TeamPlayerServiceDep
from app.schemas.common import Page
from app.schemas.form import TeamFormOut
from app.schemas.match import MatchSummary
from app.schemas.player import PlayerOut
from app.schemas.statistics import TeamStatisticsOut
from app.schemas.team import TeamDetail
from app.services.football_service import NotFoundError

router = APIRouter()


@router.get("/{team_id}", response_model=TeamDetail)
async def get_team(team_id: int, service: FootballServiceDep) -> TeamDetail:
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


@router.get("/{team_id}/players", response_model=list[PlayerOut])
async def get_team_squad(team_id: int, service: TeamPlayerServiceDep) -> list[PlayerOut]:
    try:
        return await service.get_squad(team_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc


@router.get("/{team_id}/statistics", response_model=TeamStatisticsOut)
async def get_team_statistics(team_id: int, service: TeamPlayerServiceDep) -> TeamStatisticsOut:
    try:
        return await service.get_team_statistics(team_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc


@router.get("/{team_id}/form", response_model=TeamFormOut)
async def get_team_form(
    team_id: int,
    teams: FootballServiceDep,
    service: FormServiceDep,
    scope: Literal["overall", "home", "away"] = "overall",
) -> TeamFormOut:
    try:
        await teams.get_team(team_id)  # 404 for an unknown team rather than an empty form
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc
    return await service.get_team_form(team_id, scope)
