import logging
from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.deps import (
    ArticleServiceDep,
    FootballServiceDep,
    FormServiceDep,
    InsightsServiceDep,
    PaginationDep,
    ProviderDep,
    TeamPlayerServiceDep,
)
from app.schemas.article import ArticleSummary
from app.schemas.common import Page
from app.schemas.form import TeamFormOut
from app.schemas.injury import InjuryOut, TeamInjuriesOut
from app.schemas.match import MatchSummary
from app.schemas.player import PlayerOut
from app.schemas.statistics import TeamStatisticsOut
from app.schemas.team import TeamDetail
from app.services.football_service import NotFoundError
from app.services.insights_service import TeamInsightsOut
from app.services.providers.base import FootballDataProvider, ProviderQuotaExhausted

logger = logging.getLogger(__name__)
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


@router.get("/{team_id}/injuries", response_model=TeamInjuriesOut)
async def get_team_injuries(team_id: int, teams: FootballServiceDep, provider: ProviderDep) -> TeamInjuriesOut:
    """Current absences, read through from the data provider (cached there);
    nothing is stored. An unreachable provider reads as "no known injuries"."""
    try:
        team = await teams._get_team_by_id(team_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc
    if type(provider).get_team_injuries is FootballDataProvider.get_team_injuries:
        return TeamInjuriesOut(supported=False, items=[])
    try:
        injuries = await provider.get_team_injuries(team.provider_id)
    except ProviderQuotaExhausted:
        injuries = []
    except Exception:  # the page must render without the provider
        logger.warning("injuries unavailable for team %s", team_id, exc_info=True)
        injuries = []
    return TeamInjuriesOut(
        supported=True,
        items=[
            InjuryOut(
                player_name=i.player.name,
                photo_url=i.player.photo_url,
                kind=i.kind,
                reason=i.reason,
                match_date=i.match_date,
            )
            for i in injuries
        ],
    )


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


@router.get("/{team_id}/news", response_model=Page[ArticleSummary])
async def get_team_news(team_id: int, articles: ArticleServiceDep, pagination: PaginationDep) -> Page[ArticleSummary]:
    """Published articles explicitly linked to this team."""
    page, page_size = pagination
    try:
        return await articles.list_for_team(team_id, page, page_size)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc


@router.get("/{team_id}/insights", response_model=TeamInsightsOut)
async def get_team_insights(team_id: int, service: InsightsServiceDep) -> TeamInsightsOut:
    """Form summary, streaks and scoring, in sentences, from stored results only."""
    try:
        return await service.for_team(team_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc
