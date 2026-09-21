from fastapi import APIRouter, HTTPException

from app.api.deps import FootballServiceDep
from app.schemas.match import MatchDetail, MatchEventOut, MatchSummary
from app.services.football_service import NotFoundError

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
