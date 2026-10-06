from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import FootballServiceDep, PaginationDep, TeamPlayerServiceDep
from app.schemas.common import Page
from app.schemas.competition import CompetitionOut, CompetitionSeasonsOut
from app.schemas.match import MatchSummary
from app.schemas.standing import StandingEntry
from app.schemas.statistics import TopScorersOut
from app.services.football_service import NotFoundError
from app.services.season import SEASON_LABEL_PATTERN

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
    competition_id: int,
    service: FootballServiceDep,
    pagination: PaginationDep,
    scope: Literal["all", "upcoming", "results"] = "all",
) -> Page[MatchSummary]:
    """`scope=upcoming` -> Fixtures tab, `scope=results` -> Results tab (most
    recent first); the default keeps the Phase 1 behaviour."""
    page, page_size = pagination
    try:
        items, total = await service.get_competition_fixtures(competition_id, page, page_size, scope=scope)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Competition not found") from exc
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{competition_id}/standings", response_model=list[StandingEntry])
async def get_standings(
    competition_id: int,
    service: FootballServiceDep,
    season: Annotated[str | None, Query(pattern=SEASON_LABEL_PATTERN)] = None,
    group: Annotated[str | None, Query(max_length=64)] = None,
) -> list[StandingEntry]:
    """Defaults to the latest stored season; `group` narrows a group-stage
    competition to one group."""
    try:
        return await service.get_standings(competition_id, season=season, group=group)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Competition not found") from exc


@router.get("/{competition_id}/top-scorers", response_model=TopScorersOut)
async def get_top_scorers(
    competition_id: int,
    service: TeamPlayerServiceDep,
    season: Annotated[str | None, Query(pattern=SEASON_LABEL_PATTERN)] = None,
) -> TopScorersOut:
    try:
        return await service.get_top_scorers(competition_id, season)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Competition not found") from exc


@router.get("/{competition_id}/seasons", response_model=CompetitionSeasonsOut)
async def get_competition_seasons(competition_id: int, service: FootballServiceDep) -> CompetitionSeasonsOut:
    """Seasons we hold data for (newest first) -- feeds the season selector."""
    try:
        return await service.get_competition_seasons(competition_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Competition not found") from exc
