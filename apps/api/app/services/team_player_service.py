"""Team squads/statistics, player profiles/statistics and competition top
scorers (Phase 4). Same sync-vs-read split as the other services: sync
methods run in the worker/seed, read methods serve routers from the
database/cache and never call the provider."""

from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.redis_keys import RedisKeys
from app.models.competition import Competition
from app.models.match import Match
from app.models.player import Player
from app.models.standing import Standing
from app.models.statistics import PlayerMatchStatistic, PlayerSeasonStatistic
from app.models.team import Team
from app.schemas.match import MatchSummary
from app.schemas.player import PlayerDetail, PlayerOut
from app.schemas.statistics import (
    PlayerAppearanceOut,
    PlayerMatchStatsOut,
    PlayerSeasonStatsOut,
    PlayerStatisticsOut,
    TeamRef,
    TeamSeasonStatsOut,
    TeamStatisticsOut,
    TopScorerOut,
    TopScorersOut,
)
from app.services.cache import CacheAside
from app.services.football_service import FootballService, NotFoundError
from app.services.providers.base import FootballDataProvider
from app.services.season import current_season_label
from app.services.sync_requests import request_sync_once
from app.services.upsert import upsert_by_unique_fields

logger = logging.getLogger(__name__)

_POSITION_ORDER = {"Goalkeeper": 0, "Defender": 1, "Midfielder": 2, "Forward": 3}
TOP_SCORERS_LIMIT = 20
RECENT_MATCHES_LIMIT = 10


class TeamPlayerService:
    def __init__(
        self,
        db: AsyncSession,
        provider: FootballDataProvider,
        football: FootballService | None = None,
        cache: CacheAside | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.cache = cache
        self.football = football or FootballService(db=db, provider=provider)

    # -- syncing (provider -> database) ----------------------------------------

    async def sync_squad(self, team: Team) -> int:
        """Upsert a team's squad. Players the provider no longer lists for
        this team are detached from it (a transfer) -- but only when the
        provider actually returned a squad, so an empty/failed response
        never mass-detaches a real squad."""
        if not self.provider.capabilities.team_squads:
            return 0
        squad = await self.provider.get_team_squad(team.provider_id)
        if not squad:
            return 0
        seen: list[str] = []
        for provider_player in squad:
            await self.football._sync_player(provider_player, team.id, profile=True)
            seen.append(provider_player.provider_id)
        await self.db.execute(
            update(Player)
            .where(Player.team_id == team.id, Player.provider_id.notin_(seen))
            .values(team_id=None)
        )
        await self.db.flush()
        return len(seen)

    async def sync_player(self, provider_id: str) -> Player | None:
        if not self.provider.capabilities.player_profiles:
            return None
        provider_player = await self.provider.get_player(provider_id)
        if provider_player is None:
            return None
        return await self.football._sync_player(provider_player, None, profile=True)

    async def sync_top_scorers(self, competition: Competition) -> int:
        if not self.provider.capabilities.top_scorers:
            return 0
        rows = await self.provider.get_top_scorers(competition.provider_id)
        default_season = current_season_label()
        for row in rows:
            team = await self.football._sync_team(row.team) if row.team else None
            player = await self.football._sync_player(row.player, team.id if team else None)
            await upsert_by_unique_fields(
                self.db,
                PlayerSeasonStatistic,
                {
                    "player_id": player.id,
                    "competition_id": competition.id,
                    "season": row.season or default_season,
                },
                {
                    "team_id": team.id if team else None,
                    "goals": row.goals,
                    "assists": row.assists,
                    "appearances": row.appearances,
                    "penalties": row.penalties,
                },
            )
        await self.db.flush()
        return len(rows)

    # -- reads ---------------------------------------------------------------------

    async def _team(self, team_id: int) -> Team:
        team = (await self.db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
        if team is None:
            raise NotFoundError(f"Team {team_id} not found")
        return team

    async def get_squad(self, team_id: int) -> list[PlayerOut]:
        async def _load() -> list[PlayerOut]:
            team = await self._team(team_id)  # only on a cache miss; also the 404
            players = (await self.db.execute(select(Player).where(Player.team_id == team.id))).scalars().all()
            players = sorted(
                players,
                key=lambda p: (
                    _POSITION_ORDER.get(p.position or "", 99),
                    p.shirt_number if p.shirt_number is not None else 999,
                    p.name,
                ),
            )
            if self.provider.capabilities.team_squads and not any(p.profile_synced_at for p in players):
                # Only match-event/lineup stubs (or nothing) are stored: ask
                # the worker for the real squad. This runs on a cache miss
                # only, and is debounced, so it is at most hourly per team.
                await request_sync_once(self.cache, "team", team_id, lambda: _enqueue_team_sync(team.provider_id))
            return [PlayerOut.model_validate(p) for p in players]

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_list(
            RedisKeys.team_squad(team_id), PlayerOut, _load, ttl_seconds=settings.redis_static_ttl_seconds
        )

    async def get_team_statistics(self, team_id: int) -> TeamStatisticsOut:
        async def _load() -> TeamStatisticsOut:
            await self._team(team_id)  # only on a cache miss; also the 404
            stmt = (
                select(Standing)
                .where(Standing.team_id == team_id)
                .options(selectinload(Standing.competition))
                .order_by(Standing.season.desc())
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            rows.sort(key=lambda r: r.competition.name)
            rows.sort(key=lambda r: r.season, reverse=True)  # stable: newest season first, then by name
            return TeamStatisticsOut(
                seasons=[
                    TeamSeasonStatsOut(
                        competition_id=r.competition_id,
                        competition_name=r.competition.name,
                        season=r.season,
                        group=r.group_name,
                        position=r.position,
                        played=r.played,
                        won=r.won,
                        drawn=r.drawn,
                        lost=r.lost,
                        goals_for=r.goals_for,
                        goals_against=r.goals_against,
                        goal_difference=r.goals_for - r.goals_against,
                        points=r.points,
                        form=r.form,
                    )
                    for r in rows
                ]
            )

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_model(
            RedisKeys.team_statistics(team_id),
            TeamStatisticsOut,
            _load,
            ttl_seconds=settings.redis_default_ttl_seconds,
        )

    async def _player(self, player_id: int) -> Player:
        stmt = select(Player).where(Player.id == player_id).options(selectinload(Player.team))
        player = (await self.db.execute(stmt)).scalar_one_or_none()
        if player is None:
            raise NotFoundError(f"Player {player_id} not found")
        return player

    async def get_player(self, player_id: int) -> PlayerDetail:
        async def _load() -> PlayerDetail:
            player = await self._player(player_id)  # only on a cache miss; also the 404
            if player.profile_synced_at is None and self.provider.capabilities.player_profiles:
                await request_sync_once(
                    self.cache, "player", player_id, lambda: _enqueue_player_sync(player.provider_id)
                )
            return PlayerDetail.model_validate(player)

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_model(
            RedisKeys.player(player_id),
            PlayerDetail,
            _load,
            ttl_seconds=settings.redis_static_ttl_seconds,
        )

    async def get_player_statistics(self, player_id: int) -> PlayerStatisticsOut:
        async def _load() -> PlayerStatisticsOut:
            await self._player(player_id)  # only on a cache miss; also the 404
            season_rows = (
                (
                    await self.db.execute(
                        select(PlayerSeasonStatistic)
                        .where(PlayerSeasonStatistic.player_id == player_id)
                        .options(selectinload(PlayerSeasonStatistic.competition))
                        .order_by(PlayerSeasonStatistic.season.desc())
                    )
                )
                .scalars()
                .all()
            )
            appearance_rows = (
                (
                    await self.db.execute(
                        select(PlayerMatchStatistic)
                        .join(Match, Match.id == PlayerMatchStatistic.match_id)
                        .where(PlayerMatchStatistic.player_id == player_id)
                        .options(
                            selectinload(PlayerMatchStatistic.player),
                            selectinload(PlayerMatchStatistic.match).selectinload(Match.competition),
                            selectinload(PlayerMatchStatistic.match).selectinload(Match.home_team),
                            selectinload(PlayerMatchStatistic.match).selectinload(Match.away_team),
                        )
                        .order_by(Match.kickoff_time.desc())
                        .limit(RECENT_MATCHES_LIMIT)
                    )
                )
                .scalars()
                .all()
            )
            return PlayerStatisticsOut(
                seasons=[
                    PlayerSeasonStatsOut(
                        competition_id=r.competition_id,
                        competition_name=r.competition.name,
                        season=r.season,
                        team_id=r.team_id,
                        appearances=r.appearances,
                        goals=r.goals,
                        assists=r.assists,
                        penalties=r.penalties,
                    )
                    for r in season_rows
                ],
                recent_matches=[
                    PlayerAppearanceOut(
                        match=MatchSummary.model_validate(r.match),
                        stats=PlayerMatchStatsOut.model_validate(r),
                    )
                    for r in appearance_rows
                ],
            )

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_model(
            RedisKeys.player_statistics(player_id),
            PlayerStatisticsOut,
            _load,
            ttl_seconds=settings.redis_default_ttl_seconds,
        )

    async def get_top_scorers(self, competition_id: int, season: str | None = None) -> TopScorersOut:
        async def _load() -> TopScorersOut:
            competition = (
                await self.db.execute(select(Competition).where(Competition.id == competition_id))
            ).scalar_one_or_none()
            if competition is None:  # only reached on a cache miss
                raise NotFoundError(f"Competition {competition_id} not found")
            resolved = season or (
                await self.db.execute(
                    select(func.max(PlayerSeasonStatistic.season)).where(
                        PlayerSeasonStatistic.competition_id == competition_id
                    )
                )
            ).scalar_one_or_none()
            if resolved is None:
                return TopScorersOut(competition_id=competition_id, season=season, scorers=[])
            stmt = (
                select(PlayerSeasonStatistic)
                .where(
                    PlayerSeasonStatistic.competition_id == competition_id,
                    PlayerSeasonStatistic.season == resolved,
                )
                .options(selectinload(PlayerSeasonStatistic.player), selectinload(PlayerSeasonStatistic.team))
                .order_by(
                    PlayerSeasonStatistic.goals.desc(),
                    PlayerSeasonStatistic.assists.desc().nulls_last(),
                    PlayerSeasonStatistic.player_id,
                )
                .limit(TOP_SCORERS_LIMIT)
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            return TopScorersOut(
                competition_id=competition_id,
                season=resolved,
                scorers=[
                    TopScorerOut(
                        rank=rank,
                        player=PlayerOut.model_validate(r.player),
                        team=TeamRef.model_validate(r.team) if r.team else None,
                        goals=r.goals,
                        assists=r.assists,
                        appearances=r.appearances,
                        penalties=r.penalties,
                    )
                    for rank, r in enumerate(rows, start=1)
                ],
            )

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_model(
            RedisKeys.competition_top_scorers(competition_id, season),
            TopScorersOut,
            _load,
            ttl_seconds=settings.redis_default_ttl_seconds,
        )


def _enqueue_team_sync(team_provider_id: str) -> None:
    from app.worker.tasks import sync_team

    sync_team.delay(team_provider_id)


def _enqueue_player_sync(player_provider_id: str) -> None:
    from app.worker.tasks import sync_player

    sync_player.delay(player_provider_id)
