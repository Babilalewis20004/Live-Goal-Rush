"""Lightweight insights (Phase 6): form summaries, streaks and head-to-head
summaries, in plain sentences.

Everything here is arithmetic over finished matches already stored -- no
model, no prediction, no provider call. An insight is only produced when there
is enough history to say it honestly (at least 3 results for form-based ones),
and each carries the number it is based on so a client can show or test it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.form import FormResultOut, HeadToHeadOut
from app.services.cache import CacheAside
from app.services.football_service import NotFoundError
from app.services.form_service import FormService

MIN_SAMPLE = 3
FORM_WINDOW = 5
STREAK_WINDOW = 10


class Insight(BaseModel):
    key: str
    text: str
    value: float | None = None


class TeamInsightsOut(BaseModel):
    team_id: int
    team_name: str
    sample_size: int
    """How many recent finished results the insights are drawn from."""
    insights: list[Insight] = Field(default_factory=list)


class MatchInsightsOut(BaseModel):
    match_id: int
    home: TeamInsightsOut
    away: TeamInsightsOut
    head_to_head: list[Insight] = Field(default_factory=list)
    note: Literal["Historical results only. Not a prediction."] = "Historical results only. Not a prediction."


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _run(results: list[FormResultOut], predicate) -> int:
    """Length of the unbroken run of `predicate` from the most recent result back."""
    n = 0
    for r in results:  # most recent first
        if not predicate(r):
            break
        n += 1
    return n


def team_insights(name: str, results: list[FormResultOut]) -> list[Insight]:
    """`results`: most recent first. Pure function -- the unit tests drive it directly."""
    if len(results) < MIN_SAMPLE:
        return []
    out: list[Insight] = []
    last = results[:FORM_WINDOW]
    wins = sum(r.result == "W" for r in last)
    draws = sum(r.result == "D" for r in last)
    losses = sum(r.result == "L" for r in last)
    out.append(
        Insight(
            key="form_summary",
            text=f"{name}: won {wins}, drew {draws}, lost {losses} of the last {len(last)}.",
            value=wins,
        )
    )

    win_run = _run(results, lambda r: r.result == "W")
    unbeaten = _run(results, lambda r: r.result != "L")
    if win_run >= 2:
        out.append(Insight(key="win_streak", text=f"{name} have won their last {win_run} matches.", value=win_run))
    if unbeaten >= 3 and unbeaten > win_run:
        out.append(Insight(key="unbeaten_run", text=f"{name} are unbeaten in {unbeaten} matches.", value=unbeaten))
    losing = _run(results, lambda r: r.result == "L")
    if losing >= 2:
        out.append(Insight(key="losing_streak", text=f"{name} have lost their last {losing} matches.", value=losing))
    winless = _run(results, lambda r: r.result != "W")
    if winless >= 3 and winless > losing:
        out.append(Insight(key="winless_run", text=f"{name} are winless in {winless} matches.", value=winless))

    clean = sum(r.goals_against == 0 for r in last)
    if clean >= 2:
        out.append(Insight(key="clean_sheets", text=f"{name} kept {_plural(clean, 'clean sheet')} in the last {len(last)}.", value=clean))
    scoring_run = _run(results, lambda r: r.goals_for > 0)
    if scoring_run >= 4:
        out.append(Insight(key="scoring_run", text=f"{name} have scored in each of their last {scoring_run} matches.", value=scoring_run))
    blanks = sum(r.goals_for == 0 for r in last)
    if blanks >= 2:
        out.append(Insight(key="blanks", text=f"{name} failed to score in {blanks} of the last {len(last)}.", value=blanks))

    scored = sum(r.goals_for for r in last) / len(last)
    conceded = sum(r.goals_against for r in last) / len(last)
    out.append(
        Insight(
            key="goal_average",
            text=f"{name} averaged {scored:.1f} goals scored and {conceded:.1f} conceded over the last {len(last)}.",
            value=round(scored, 2),
        )
    )
    return out


def head_to_head_insights(home_name: str, away_name: str, h2h: HeadToHeadOut) -> list[Insight]:
    meetings = h2h.meetings
    if len(meetings) < MIN_SAMPLE:
        return []
    n = len(meetings)
    parts = []
    for label, wins in ((home_name, h2h.home_team_wins), (away_name, h2h.away_team_wins)):
        parts.append(f"{label} {_plural(wins, 'win')}")
    parts.append(_plural(h2h.draws, "draw"))
    out = [Insight(key="h2h_record", text=f"Last {n} meetings: {', '.join(parts)}.", value=n)]
    last = meetings[0]
    out.append(
        Insight(
            key="h2h_last",
            text=f"Most recent meeting: {last.home_team.name} {last.home_score}-{last.away_score} {last.away_team.name} ({last.kickoff_time:%d %b %Y}).",
        )
    )
    goals = sum(m.home_score + m.away_score for m in meetings) / n
    both = sum(m.home_score > 0 and m.away_score > 0 for m in meetings)
    out.append(Insight(key="h2h_goals", text=f"These meetings averaged {goals:.1f} goals; both teams scored in {both} of {n}.", value=round(goals, 2)))
    return out


class InsightsService:
    def __init__(self, db: AsyncSession, cache: CacheAside | None = None) -> None:
        self.db = db
        self.cache = cache
        self.form = FormService(db, cache)

    async def _team(self, team_id: int, name: str, before: datetime | None, exclude: int | None) -> TeamInsightsOut:
        form = await self.form._compute_team_form(team_id, "overall", STREAK_WINDOW, before, exclude)
        return TeamInsightsOut(team_id=team_id, team_name=name, sample_size=len(form.results), insights=team_insights(name, form.results))

    async def for_team(self, team_id: int) -> TeamInsightsOut:
        from app.models.team import Team

        team = await self.db.get(Team, team_id)
        if team is None:
            raise NotFoundError(f"Team {team_id} not found")

        async def load() -> TeamInsightsOut:
            return await self._team(team_id, team.name, None, None)

        if self.cache is None:
            return await load()
        return await self.cache.get_or_set_model(
            f"football:team:{team_id}:insights", TeamInsightsOut, load, ttl_seconds=settings.redis_default_ttl_seconds
        )

    async def for_match(self, match_id: int) -> MatchInsightsOut:
        match = await self.form._match(match_id)  # raises NotFoundError

        async def load() -> MatchInsightsOut:
            home = await self._team(match.home_team_id, match.home_team.name, match.kickoff_time, match.id)
            away = await self._team(match.away_team_id, match.away_team.name, match.kickoff_time, match.id)
            h2h = await self.form.get_head_to_head(match_id)
            return MatchInsightsOut(
                match_id=match_id, home=home, away=away,
                head_to_head=head_to_head_insights(match.home_team.name, match.away_team.name, h2h),
            )

        if self.cache is None:
            return await load()
        return await self.cache.get_or_set_model(
            f"football:match:{match_id}:insights", MatchInsightsOut, load, ttl_seconds=settings.redis_static_ttl_seconds
        )
