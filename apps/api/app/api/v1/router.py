from fastapi import APIRouter

from app.api.v1 import competitions, matches, search, teams

api_router = APIRouter()
api_router.include_router(matches.router, prefix="/matches", tags=["matches"])
api_router.include_router(competitions.router, prefix="/competitions", tags=["competitions"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
