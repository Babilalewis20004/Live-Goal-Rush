from fastapi import APIRouter

from app.api.v1 import auth, competitions, devices, favourites, matches, notifications, search, teams, users

api_router = APIRouter()
api_router.include_router(matches.router, prefix="/matches", tags=["matches"])
api_router.include_router(competitions.router, prefix="/competitions", tags=["competitions"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(favourites.router, prefix="/favourites", tags=["favourites"])
api_router.include_router(devices.router, prefix="/devices", tags=["devices"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
