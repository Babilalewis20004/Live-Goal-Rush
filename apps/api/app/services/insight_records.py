"""Persisted insights (Phase 6b): generation, storage, live and player insights.

Insights are sentences computed from stored, verified results/statistics (see
`insights_service` for the form/streak/head-to-head ones). Here they are stored
as `InsightRecord`s with a `source_data_version` -- a fingerprint of the exact
rows they were computed from -- so that:

* the generation job is idempotent: unchanged data -> nothing rewritten;
* every insight can be traced to the data it came from;
* a stale insight can never outlive the data that supported it (the set for an
  entity is replaced as a whole when its source data changes).

Nothing here guesses. An insight needs a minimum sample, and live insights need
the statistic for *both* teams.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.community import publish_match_event
from app.events.schemas import RealtimeEventType
from app.models.analytics import InsightRecord
from app.models.enums import InsightEntityType, MatchStatus
from app.models.match import Match
from app.models.player import Player
from app.models.statistics import MatchStatistic, PlayerMatchStatistic
from app.models.team import Team
from app.services.football_service import NotFoundError
from app.services.insights_service import Insight, InsightsService
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

LIVE_STATUSES = (MatchStatus.LIVE, MatchStatus.HALFTIME)
PLAYER_WINDOW = 10
MIN_PLAYER_MATCHES = 3


def _version(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def live_insights(home_name: str, away_name: str, home: MatchStatistic | None, away: MatchStatistic | None) -> list[Insight]:
    """Only statements both teams' live statistics support."""
    if home is None or away is None:
        return []
    out: list[Insight] = []
    if home.shots is not None and away.shots is not None and home.shots + away.shots >= 6:
        lead, trail, ln, tn = (home, away, home_name, away_name) if home.shots >= away.shots else (away, home, away_name, home_name)
        if lead.shots > trail.shots:
            out.append(Insight(key="live_shots", text=f"{ln} have had {lead.shots} shots to {tn}'s {trail.shots}.", value=float(lead.shots - trail.shots)))
    if home.possession is not None and away.possession is not None:
        top, name = (home.possession, home_name) if home.possession >= away.possession else (away.possession, away_name)
        if top >= 60:
            out.append(Insight(key="live_possession", text=f"{name} are dominating possession with {top:.0f}%.", value=float(top)))
    if (
        home.shots_on_target is not None and away.shots_on_target is not None
        and home.shots_on_target + away.shots_on_target >= 4 and home.shots_on_target != away.shots_on_target
    ):
        lead, ln = (home, home_name) if home.shots_on_target > away.shots_on_target else (away, away_name)
        other = away if lead is home else home
        out.append(Insight(key="live_on_target", text=f"{ln} lead on shots on target, {lead.shots_on_target} to {other.shots_on_target}.", value=float(lead.shots_on_target - other.shots_on_target)))
    return out


class InsightGenerator:
    def __init__(self, db: AsyncSession, redis=None) -> None:
        self.db = db
        self.redis = redis
        self.insights = InsightsService(db, None)  # compute fresh: this is the job, not a request

    # -- storage ----------------------------------------------------------------------------

    async def _store(self, entity: InsightEntityType, entity_id: int, items: dict[str, Insight], version: str) -> bool:
        """Replace the entity's insights if (and only if) the source data changed.
        Returns True when something was written."""
        current = (
            await self.db.execute(
                select(InsightRecord).where(InsightRecord.entity_type == entity, InsightRecord.entity_id == entity_id)
            )
        ).scalars().all()
        if not current and not items:
            return False  # nothing stored, nothing to say: not a write, not counted
        if current and {r.source_data_version for r in current} == {version} and {r.insight_type for r in current} == set(items):
            return False
        await self.db.execute(
            delete(InsightRecord).where(InsightRecord.entity_type == entity, InsightRecord.entity_id == entity_id)
        )
        for insight_type, ins in items.items():
            self.db.add(
                InsightRecord(
                    entity_type=entity, entity_id=entity_id, insight_type=insight_type, text=ins.text[:300],
                    value=ins.value, source_data_version=version, generated_at=datetime.now(timezone.utc),
                )
            )
        await self.db.commit()
        metrics.count("insight_generation_total", max(len(items), 1))
        return True

    async def read(self, entity: InsightEntityType, entity_id: int) -> list[InsightRecord]:
        return list(
            (
                await self.db.execute(
                    select(InsightRecord)
                    .where(InsightRecord.entity_type == entity, InsightRecord.entity_id == entity_id)
                    .order_by(InsightRecord.insight_type)
                )
            ).scalars()
        )

    # -- generation -----------------------------------------------------------------------------

    async def _team_fingerprint(self, team_id: int, before: datetime | None = None) -> str:
        conditions = [
            Match.status == MatchStatus.FINISHED,
            (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
        ]
        if before is not None:
            conditions.append(Match.kickoff_time < before)
        newest, count = (
            await self.db.execute(select(func.max(Match.kickoff_time), func.count()).where(*conditions))
        ).one()
        return f"{newest.isoformat() if newest else '-'}:{count}"

    async def generate_for_match(self, match_id: int) -> int:
        match = (await self.db.execute(select(Match).where(Match.id == match_id))).scalar_one_or_none()
        if match is None:
            raise NotFoundError(f"Match {match_id} not found")
        home = await self.db.get(Team, match.home_team_id)
        away = await self.db.get(Team, match.away_team_id)
        pre = await self.insights.for_match(match_id)
        items: dict[str, Insight] = {}
        for side, block in (("home", pre.home), ("away", pre.away)):
            for ins in block.insights:
                items[f"{side}:{ins.key}"] = ins
        for ins in pre.head_to_head:
            items[f"h2h:{ins.key}"] = ins

        stats_stamp = "-"
        if match.status in LIVE_STATUSES:
            rows = {
                s.team_id: s
                for s in (await self.db.execute(select(MatchStatistic).where(MatchStatistic.match_id == match_id))).scalars()
            }
            for ins in live_insights(home.name, away.name, rows.get(home.id), rows.get(away.id)):
                items[f"live:{ins.key}"] = ins
            stats_stamp = max((s.updated_at.isoformat() for s in rows.values()), default="-")

        version = _version(
            "match", match_id, match.status.value, stats_stamp,
            await self._team_fingerprint(match.home_team_id, match.kickoff_time),
            await self._team_fingerprint(match.away_team_id, match.kickoff_time),
        )
        wrote = await self._store(InsightEntityType.MATCH, match_id, items, version)
        if wrote:
            await publish_match_event(self.redis, RealtimeEventType.MATCH_INSIGHT_UPDATED, match_id, throttle=False)
        return len(items) if wrote else 0

    async def generate_for_team(self, team_id: int) -> int:
        team = await self.db.get(Team, team_id)
        if team is None:
            raise NotFoundError(f"Team {team_id} not found")
        block = await self.insights.for_team(team_id)
        items = {i.key: i for i in block.insights}
        version = _version("team", team_id, await self._team_fingerprint(team_id))
        wrote = await self._store(InsightEntityType.TEAM, team_id, items, version)
        return len(items) if wrote else 0

    async def player_insight_items(self, player_id: int) -> tuple[dict[str, Insight], str]:
        player = await self.db.get(Player, player_id)
        if player is None:
            raise NotFoundError(f"Player {player_id} not found")
        rows = (
            await self.db.execute(
                select(PlayerMatchStatistic, Match.kickoff_time)
                .join(Match, Match.id == PlayerMatchStatistic.match_id)
                .where(PlayerMatchStatistic.player_id == player_id, Match.status == MatchStatus.FINISHED)
                .order_by(Match.kickoff_time.desc())
                .limit(PLAYER_WINDOW)
            )
        ).all()
        items: dict[str, Insight] = {}
        played = [ps for ps, _ in rows if (ps.minutes_played or 0) > 0 and ps.goals is not None]
        if len(played) >= MIN_PLAYER_MATCHES:
            scored = sum(ps.goals > 0 for ps in played)
            if scored:
                items["scored_in"] = Insight(
                    key="scored_in", text=f"{player.name} has scored in {scored} of the last {len(played)} matches played.", value=float(scored)
                )
            goals = sum(ps.goals for ps in played)
            if goals:
                items["goals_recent"] = Insight(key="goals_recent", text=f"{player.name} has {goals} goal{'s' if goals != 1 else ''} in their last {len(played)} appearances.", value=float(goals))

        # Most chances created in the player's team, over the same window of that team's matches.
        own = next((ps for ps, _ in rows), None)
        if own is not None and own.key_passes is not None:
            totals = (
                await self.db.execute(
                    select(PlayerMatchStatistic.player_id, func.sum(PlayerMatchStatistic.key_passes), func.count())
                    .where(PlayerMatchStatistic.team_id == own.team_id, PlayerMatchStatistic.key_passes.is_not(None))
                    .group_by(PlayerMatchStatistic.player_id)
                    .having(func.count() >= MIN_PLAYER_MATCHES)
                    .order_by(func.sum(PlayerMatchStatistic.key_passes).desc())
                    .limit(2)
                )
            ).all()
            if totals and totals[0][0] == player_id and totals[0][1] and (len(totals) == 1 or totals[0][1] > totals[1][1]):
                team = await self.db.get(Team, own.team_id)
                items["most_chances"] = Insight(
                    key="most_chances", text=f"{player.name} has created the most chances for {team.name} in the matches on record ({totals[0][1]}).", value=float(totals[0][1])
                )
        newest = rows[0][1].isoformat() if rows else "-"
        return items, _version("player", player_id, newest, len(rows), sum(ps.key_passes or 0 for ps, _ in rows))

    async def generate_for_player(self, player_id: int) -> int:
        items, version = await self.player_insight_items(player_id)
        wrote = await self._store(InsightEntityType.PLAYER, player_id, items, version)
        return len(items) if wrote else 0
