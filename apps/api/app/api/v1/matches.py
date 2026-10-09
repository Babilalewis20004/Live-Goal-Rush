from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.deps import InsightsServiceDep, ArticleServiceDep, FootballServiceDep, FormServiceDep, MatchCentreServiceDep, PaginationDep
from app.schemas.article import ArticleSummary
from app.schemas.common import Page
from app.schemas.form import HeadToHeadOut, MatchFormOut
from app.schemas.lineup import MatchLineupsOut
from app.schemas.match import MatchDetail, MatchEventOut, MatchSummary
from app.schemas.statistics import MatchPlayerStatisticsOut, MatchStatisticsOut
from app.services.football_service import NotFoundError
from app.services.insights_service import MatchInsightsOut

router = APIRouter()


@router.get("/live", response_model=list[MatchSummary])
async def get_live_matches(service: FootballServiceDep) -> list[MatchSummary]:
    return await service.get_live_matches()


@router.get("/today", response_model=list[MatchSummary])
async def get_today_matches(service: FootballServiceDep) -> list[MatchSummary]:
    return await service.get_today_matches()


@router.get("/upcoming", response_model=list[MatchSummary])
async def get_upcoming_matches(service: FootballServiceDep) -> list[MatchSummary]:
    return await service.get_upcoming_matches()


@router.get("/{match_id}", response_model=MatchDetail)
async def get_match(match_id: int, service: FootballServiceDep) -> MatchDetail:
    try:
        return await service.get_match(match_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@router.get("/{match_id}/events", response_model=list[MatchEventOut])
async def get_match_events(match_id: int, service: FootballServiceDep) -> list[MatchEventOut]:
    try:
        return await service.get_match_events(match_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@router.get("/{match_id}/lineups", response_model=MatchLineupsOut)
async def get_match_lineups(match_id: int, service: MatchCentreServiceDep) -> MatchLineupsOut:
    try:
        return await service.get_lineups(match_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@router.get("/{match_id}/statistics", response_model=MatchStatisticsOut)
async def get_match_statistics(match_id: int, service: MatchCentreServiceDep) -> MatchStatisticsOut:
    try:
        return await service.get_statistics(match_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@router.get("/{match_id}/players", response_model=MatchPlayerStatisticsOut)
async def get_match_player_statistics(
    match_id: int, service: MatchCentreServiceDep
) -> MatchPlayerStatisticsOut:
    try:
        return await service.get_player_statistics(match_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@router.get("/{match_id}/form", response_model=MatchFormOut)
async def get_match_form(
    match_id: int, service: FormServiceDep, scope: Literal["overall", "venue"] = "overall"
) -> MatchFormOut:
    try:
        return await service.get_match_form(match_id, scope)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@router.get("/{match_id}/head-to-head", response_model=HeadToHeadOut)
async def get_match_head_to_head(match_id: int, service: FormServiceDep) -> HeadToHeadOut:
    try:
        return await service.get_head_to_head(match_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@router.get("/{match_id}/news", response_model=Page[ArticleSummary])
async def get_match_news(match_id: int, articles: ArticleServiceDep, pagination: PaginationDep) -> Page[ArticleSummary]:
    """News for the match page: articles about this match, then its teams, then its
    competition -- each tagged with how it relates. Nothing unrelated."""
    page, page_size = pagination
    try:
        return await articles.list_for_match(match_id, page, page_size)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@router.get("/{match_id}/insights", response_model=MatchInsightsOut)
async def get_match_insights(match_id: int, service: InsightsServiceDep) -> MatchInsightsOut:
    """Both teams' form and streaks going into the match, plus a head-to-head summary.
    Historical results only -- not a prediction."""
    try:
        return await service.for_match(match_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc
