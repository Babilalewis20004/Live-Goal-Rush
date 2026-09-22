"""Favourites business logic (Phase 3 §8/§9/§10).

Ownership is always enforced in the query itself (`WHERE user_id == ...`),
never "load then check in Python" -- the discipline every later
user-owned-resource service in this codebase should follow. Adding a
favourite is idempotent (`ON CONFLICT DO NOTHING` against each table's
unique constraint) rather than check-then-insert, so a double-click can't
race into an IntegrityError.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.competition import Competition
from app.models.favourite import FavouriteCompetition, FavouriteMatch, FavouriteTeam
from app.models.match import Match
from app.models.team import Team
from app.services.football_service import NotFoundError
from app.worker.tasks import sync_team

logger = logging.getLogger(__name__)

_MATCH_LOAD_OPTIONS = (
    selectinload(FavouriteMatch.match).selectinload(Match.competition),
    selectinload(FavouriteMatch.match).selectinload(Match.home_team),
    selectinload(FavouriteMatch.match).selectinload(Match.away_team),
)


class FavouritesService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_favourites(
        self, user_id: int
    ) -> tuple[list[FavouriteTeam], list[FavouriteCompetition], list[FavouriteMatch]]:
        teams_result = await self._db.execute(
            select(FavouriteTeam)
            .where(FavouriteTeam.user_id == user_id)
            .options(selectinload(FavouriteTeam.team))
            .order_by(FavouriteTeam.created_at)
        )
        competitions_result = await self._db.execute(
            select(FavouriteCompetition)
            .where(FavouriteCompetition.user_id == user_id)
            .options(selectinload(FavouriteCompetition.competition))
            .order_by(FavouriteCompetition.created_at)
        )
        matches_result = await self._db.execute(
            select(FavouriteMatch)
            .where(FavouriteMatch.user_id == user_id)
            .options(*_MATCH_LOAD_OPTIONS)
            .order_by(FavouriteMatch.created_at)
        )
        return (
            list(teams_result.scalars().all()),
            list(competitions_result.scalars().all()),
            list(matches_result.scalars().all()),
        )

    # -- teams ----------------------------------------------------------------

    async def add_team(self, user_id: int, team_id: int) -> None:
        team = await self._db.get(Team, team_id)
        if team is None:
            raise NotFoundError()
        stmt = (
            pg_insert(FavouriteTeam)
            .values(user_id=user_id, team_id=team_id)
            .on_conflict_do_nothing(index_elements=["user_id", "team_id"])
        )
        await self._db.execute(stmt)
        await self._db.commit()
        logger.info("User id=%s favourited team id=%s", user_id, team_id)
        try:
            # On-demand sync (the exact hook worker/tasks.py's sync_team
            # docstring already calls out) -- best-effort: a broker hiccup
            # shouldn't fail the favourite itself, the next scheduled poll
            # will pick this team up regardless.
            sync_team.delay(team.provider_id)
        except Exception:
            logger.warning("Failed to enqueue sync_team for team id=%s", team_id, exc_info=True)

    async def remove_team(self, user_id: int, team_id: int) -> None:
        await self._db.execute(
            delete(FavouriteTeam).where(FavouriteTeam.user_id == user_id, FavouriteTeam.team_id == team_id)
        )
        await self._db.commit()

    # -- competitions -----------------------------------------------------------

    async def add_competition(self, user_id: int, competition_id: int) -> None:
        competition = await self._db.get(Competition, competition_id)
        if competition is None:
            raise NotFoundError()
        stmt = (
            pg_insert(FavouriteCompetition)
            .values(user_id=user_id, competition_id=competition_id)
            .on_conflict_do_nothing(index_elements=["user_id", "competition_id"])
        )
        await self._db.execute(stmt)
        await self._db.commit()
        logger.info("User id=%s favourited competition id=%s", user_id, competition_id)

    async def remove_competition(self, user_id: int, competition_id: int) -> None:
        await self._db.execute(
            delete(FavouriteCompetition).where(
                FavouriteCompetition.user_id == user_id,
                FavouriteCompetition.competition_id == competition_id,
            )
        )
        await self._db.commit()

    # -- matches ----------------------------------------------------------------

    async def add_match(self, user_id: int, match_id: int) -> None:
        match = await self._db.get(Match, match_id)
        if match is None:
            raise NotFoundError()
        stmt = (
            pg_insert(FavouriteMatch)
            .values(user_id=user_id, match_id=match_id)
            .on_conflict_do_nothing(index_elements=["user_id", "match_id"])
        )
        await self._db.execute(stmt)
        await self._db.commit()
        logger.info("User id=%s favourited match id=%s", user_id, match_id)

    async def remove_match(self, user_id: int, match_id: int) -> None:
        await self._db.execute(
            delete(FavouriteMatch).where(
                FavouriteMatch.user_id == user_id, FavouriteMatch.match_id == match_id
            )
        )
        await self._db.commit()
