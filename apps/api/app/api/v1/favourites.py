from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUserDep, FavouritesServiceDep
from app.schemas.favourite import (
    FavouriteCompetitionOut,
    FavouriteMatchOut,
    FavouriteTeamOut,
    FavouritesOut,
)
from app.services.football_service import NotFoundError

router = APIRouter()


@router.get("", response_model=FavouritesOut)
async def list_favourites(current_user: CurrentUserDep, service: FavouritesServiceDep) -> FavouritesOut:
    teams, competitions, matches = await service.list_favourites(current_user.id)
    return FavouritesOut(
        teams=[FavouriteTeamOut.model_validate(row) for row in teams],
        competitions=[FavouriteCompetitionOut.model_validate(row) for row in competitions],
        matches=[FavouriteMatchOut.model_validate(row) for row in matches],
    )


@router.post("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def follow_team(team_id: int, current_user: CurrentUserDep, service: FavouritesServiceDep) -> None:
    try:
        await service.add_team(current_user.id, team_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_team(team_id: int, current_user: CurrentUserDep, service: FavouritesServiceDep) -> None:
    await service.remove_team(current_user.id, team_id)


@router.post("/competitions/{competition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def follow_competition(
    competition_id: int, current_user: CurrentUserDep, service: FavouritesServiceDep
) -> None:
    try:
        await service.add_competition(current_user.id, competition_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Competition not found") from exc


@router.delete("/competitions/{competition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_competition(
    competition_id: int, current_user: CurrentUserDep, service: FavouritesServiceDep
) -> None:
    await service.remove_competition(current_user.id, competition_id)


@router.post("/matches/{match_id}", status_code=status.HTTP_204_NO_CONTENT)
async def follow_match(match_id: int, current_user: CurrentUserDep, service: FavouritesServiceDep) -> None:
    try:
        await service.add_match(current_user.id, match_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@router.delete("/matches/{match_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_match(match_id: int, current_user: CurrentUserDep, service: FavouritesServiceDep) -> None:
    await service.remove_match(current_user.id, match_id)
