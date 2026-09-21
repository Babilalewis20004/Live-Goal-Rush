from fastapi import APIRouter, HTTPException

from app.api.deps import FootballServiceDep, PaginationDep
from app.schemas.common import Page
from app.schemas.competition import CompetitionOut
from app.schemas.match import MatchSummary
from app.schemas.standing import StandingEntry
from app.services.football_service import NotFoundError

router = APIRouter()


@router.get("", response_model=Page[CompetitionOut])
async def list_competitions(
    service: FootballServiceDep, pagination: PaginationDep
) -> Page[CompetitionOut]:
    page, page_size = pagination
    items, total = await service.list_competitions(page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{competition_id}", response_model=CompetitionOut)
async def get_competition(competition_id: int, service: FootballServiceDep) -> CompetitionOut:
    try:
        return await service.get_competition(competition_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Competition not found") from exc


@router.get("/{competition_id}/fixtures", response_model=Page[MatchSummary])
async def get_competition_fixtures(
    competition_id: int, service: FootballServiceDep, pagination: PaginationDep
) -> Page[MatchSummary]:
    page, page_size = pagination
    try:
        items, total = await service.get_competition_fixtures(competition_id, page, page_size)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Competition not found") from exc
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{competition_id}/standings", response_model=list[StandingEntry])
async def get_standings(competition_id: int, service: FootballServiceDep) -> list[StandingEntry]:
    try:
        return await service.get_standings(competition_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Competition not found") from exc
