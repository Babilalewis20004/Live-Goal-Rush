"""Team form and head-to-head (Phase 4 §16/§17).

Both are *derived from stored finished matches* -- no provider call, no
provider capability needed -- and are historical information only: nothing
here predicts anything. A team with no stored results simply gets an empty
form; the UI says so rather than inventing a streak.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.redis_keys import RedisKeys
from app.models.enums import MatchStatus
from app.models.match import Match
from app.schemas.competition import CompetitionOut
from app.schemas.form import (
    FormResultOut,
    FormSummaryOut,
    HeadToHeadMeetingOut,
    HeadToHeadOut,
    MatchFormOut,
    TeamFormOut,
)
from app.schemas.team import TeamOut
from app.services.analytics_math import Result, summarise_form
from app.services.cache import CacheAside
from app.services.football_service import NotFoundError

FORM_LIMIT = 5
H2H_LIMIT = 5
H2H_LOOKBACK_YEARS = 10

_TEAM_SCOPES = ("overall", "home", "away")
FORM_LIMITS = (5, 10)
H2H_WINDOWS: dict[str, int | None] = {"last5": 5, "last10": 10, "all": None}
H2H_ALL_LOOKBACK_YEARS = 50
_LOAD = (
    selectinload(Match.competition),
    selectinload(Match.home_team),
    selectinload(Match.away_team),
)


class FormService:
    def __init__(self, db: AsyncSession, cache: CacheAside | None = None) -> None:
        self.db = db
        self.cache = cache

    async def _match(self, match_id: int) -> Match:
        match = (
            await self.db.execute(select(Match).where(Match.id == match_id).options(*_LOAD))
        ).scalar_one_or_none()
        if match is None:
            raise NotFoundError(f"Match {match_id} not found")
        return match

    async def _compute_team_form(
        self, team_id: int, scope: str, limit: int, before: datetime | None, exclude_match_id: int | None
    ) -> TeamFormOut:
        if scope == "home":
            side = Match.home_team_id == team_id
        elif scope == "away":
            side = Match.away_team_id == team_id
        else:
            side = or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
        conditions = [Match.status == MatchStatus.FINISHED, side]
        if before is not None:
            conditions.append(Match.kickoff_time < before)
        if exclude_match_id is not None:
            conditions.append(Match.id != exclude_match_id)

        stmt = select(Match).where(*conditions).options(*_LOAD).order_by(Match.kickoff_time.desc()).limit(limit)
        matches = (await self.db.execute(stmt)).scalars().all()

        results: list[FormResultOut] = []
        for m in matches:
            is_home = m.home_team_id == team_id
            goals_for, goals_against = (m.home_score, m.away_score) if is_home else (m.away_score, m.home_score)
            results.append(
                FormResultOut(
                    match_id=m.id,
                    result="W" if goals_for > goals_against else "D" if goals_for == goals_against else "L",
                    venue="home" if is_home else "away",
                    opponent=TeamOut.model_validate(m.away_team if is_home else m.home_team),
                    goals_for=goals_for,
                    goals_against=goals_against,
                    kickoff_time=m.kickoff_time,
                    competition=CompetitionOut.model_validate(m.competition),
                )
            )
        summary = summarise_form([Result(r.goals_for, r.goals_against) for r in results], limit)
        return TeamFormOut(
            team_id=team_id,
            scope=scope,
            limit=limit,
            results=results,
            sequence="".join(r.result for r in reversed(results)),
            summary=FormSummaryOut(**summary.__dict__),
        )

    async def get_team_form(self, team_id: int, scope: str = "overall", limit: int = FORM_LIMIT) -> TeamFormOut:
        """Current form (most recent finished results). Cached briefly; the
        worker invalidates it when one of the team's matches finishes."""
        if scope not in _TEAM_SCOPES:
            raise ValueError(f"Unknown form scope {scope!r}")
        if limit not in FORM_LIMITS:
            raise ValueError(f"Form window must be one of {FORM_LIMITS}")

        async def _load() -> TeamFormOut:
            return await self._compute_team_form(team_id, scope, limit, None, None)

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_model(
            RedisKeys.team_form(team_id, scope, limit), TeamFormOut, _load, ttl_seconds=settings.redis_default_ttl_seconds
        )

    async def get_match_form(self, match_id: int, scope: str = "overall") -> MatchFormOut:
        """Form going into a match: results strictly before its kickoff.
        `scope="venue"` = the home side's home results and the away side's
        away results. That window never changes once the match has been
        played, hence the long TTL."""
        if scope not in ("overall", "venue"):
            raise ValueError(f"Unknown match form scope {scope!r}")

        async def _load() -> MatchFormOut:
            match = await self._match(match_id)  # only on a cache miss; also the 404
            home_scope, away_scope = ("home", "away") if scope == "venue" else ("overall", "overall")
            return MatchFormOut(
                home=await self._compute_team_form(
                    match.home_team_id, home_scope, FORM_LIMIT, match.kickoff_time, match.id
                ),
                away=await self._compute_team_form(
                    match.away_team_id, away_scope, FORM_LIMIT, match.kickoff_time, match.id
                ),
            )

        if self.cache is None:
            return await _load()
        key = RedisKeys.match_form(match_id) + (":venue" if scope == "venue" else "")
        return await self.cache.get_or_set_model(
            key, MatchFormOut, _load, ttl_seconds=settings.redis_static_ttl_seconds
        )

    async def get_head_to_head(self, match_id: int, window: str = "last5") -> HeadToHeadOut:
        if window not in H2H_WINDOWS:
            raise ValueError(f"Head-to-head window must be one of {tuple(H2H_WINDOWS)}")
        limit = H2H_WINDOWS[window]

        async def _load() -> HeadToHeadOut:
            match = await self._match(match_id)  # only on a cache miss; also the 404
            home_id, away_id = match.home_team_id, match.away_team_id
            years = H2H_ALL_LOOKBACK_YEARS if limit is None else H2H_LOOKBACK_YEARS
            period_start = match.kickoff_time - timedelta(days=365 * years)
            stmt = (
                select(Match)
                .where(
                    Match.status == MatchStatus.FINISHED,
                    Match.kickoff_time < match.kickoff_time,
                    Match.kickoff_time >= period_start,
                    Match.id != match.id,
                    or_(
                        and_(Match.home_team_id == home_id, Match.away_team_id == away_id),
                        and_(Match.home_team_id == away_id, Match.away_team_id == home_id),
                    ),
                )
                .options(*_LOAD)
                .order_by(Match.kickoff_time.desc())
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            meetings = (await self.db.execute(stmt)).scalars().all()

            home_wins = draws = away_wins = 0
            home_goals = away_goals = 0
            letters: list[str] = []  # most recent first, from the match's home team's point of view
            for m in meetings:
                mine, theirs = (m.home_score, m.away_score) if m.home_team_id == home_id else (m.away_score, m.home_score)
                home_goals += mine
                away_goals += theirs
                if mine == theirs:
                    draws += 1
                    letters.append("D")
                elif mine > theirs:
                    home_wins += 1
                    letters.append("W")
                else:
                    away_wins += 1
                    letters.append("L")
            n = len(meetings)
            complete = limit is None or n >= limit
            limitation = None if complete else f"Only {n} of the last {limit} meetings are stored."
            return HeadToHeadOut(
                home_team_id=home_id,
                away_team_id=away_id,
                limit=limit,
                window=window,
                total_meetings=n,
                home_team_goals=home_goals,
                away_team_goals=away_goals,
                average_goals=round((home_goals + away_goals) / n, 2) if n else None,
                recent_form="".join(reversed(letters)),
                complete=complete,
                limitation=limitation,
                period_start=period_start,
                before=match.kickoff_time,
                meetings=[
                    HeadToHeadMeetingOut(
                        match_id=m.id,
                        kickoff_time=m.kickoff_time,
                        competition=CompetitionOut.model_validate(m.competition),
                        home_team=TeamOut.model_validate(m.home_team),
                        away_team=TeamOut.model_validate(m.away_team),
                        home_score=m.home_score,
                        away_score=m.away_score,
                    )
                    for m in meetings
                ],
                home_team_wins=home_wins,
                draws=draws,
                away_team_wins=away_wins,
            )

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_model(
            RedisKeys.match_head_to_head(match_id, window),
            HeadToHeadOut,
            _load,
            ttl_seconds=settings.redis_static_ttl_seconds,
        )


__all__ = ["FormService", "FORM_LIMIT", "H2H_LIMIT", "H2H_LOOKBACK_YEARS"]
