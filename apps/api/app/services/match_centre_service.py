"""Match-centre data: lineups, team statistics, player statistics (Phase 4).

Same split as `FootballService`: **sync** methods (provider -> database) are
only called by the worker / seed; **read** methods (database/cache -> API
schema) are what routers call and never touch the provider. Every sync
method checks the provider's declared capability first and treats an empty
provider answer as "nothing new" -- it never deletes stored data because a
provider momentarily returned nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.redis_keys import RedisKeys
from app.models.enums import MatchEventType, MatchStatus
from app.models.lineup import LineupPlayer, MatchLineup
from app.models.match import Match
from app.models.match_event import MatchEvent
from app.models.player import Player
from app.models.statistics import MatchStatistic, PlayerMatchStatistic
from app.schemas.lineup import LineupPlayerOut, MatchLineupsOut, TeamLineupOut
from app.schemas.player import PlayerOut
from app.schemas.statistics import (
    MatchPlayerStatisticsOut,
    MatchStatisticsOut,
    PlayerMatchStatsOut,
    TeamMatchStatsOut,
)
from app.schemas.team import TeamOut
from app.services.cache import CacheAside
from app.services.football_service import FootballService, NotFoundError
from app.services.providers.base import FootballDataProvider

logger = logging.getLogger(__name__)

_STAT_FIELDS = (
    "possession",
    "shots",
    "shots_on_target",
    "corners",
    "fouls",
    "offsides",
    "yellow_cards",
    "red_cards",
    "pass_accuracy",
    "expected_goals",
)
_PLAYER_STAT_FIELDS = (
    "minutes_played",
    "goals",
    "assists",
    "shots",
    "shots_on_target",
    "passes",
    "pass_accuracy",
    "key_passes",
    "tackles",
    "interceptions",
    "clearances",
    "blocks",
    "yellow_cards",
    "red_cards",
    "fouls_committed",
)


def cache_ttl_for_status(status: MatchStatus | str) -> int:
    """How long match-centre data may be cached, by how fast it can still
    change: live data tracks the poll interval, upcoming data is slow, and
    a finished match's data is effectively static (the worker also
    invalidates on every change, so the TTL is only a backstop)."""
    value = status.value if isinstance(status, MatchStatus) else status
    if value in ("live", "halftime"):
        return settings.redis_live_match_ttl_seconds
    if value == "scheduled":
        return settings.redis_default_ttl_seconds
    return settings.redis_static_ttl_seconds


class MatchCentreService:
    def __init__(
        self,
        db: AsyncSession,
        provider: FootballDataProvider,
        cache: CacheAside | None = None,
        football: FootballService | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.cache = cache
        self.football = football or FootballService(db=db, provider=provider)

    # -- syncing (provider -> database) ----------------------------------------
    #
    # These run on every live poll, so they load the match's existing rows
    # in one query and only assign changed values (SQLAlchemy emits an
    # UPDATE only for attributes whose value actually differs) instead of
    # doing a SELECT + UPSERT round trip per player.

    async def _resolve_players(self, provider_players, team_id: int) -> dict[str, Player]:
        """provider_id -> Player for every player in the payload, creating
        the ones we haven't seen. Existing players are left as they are --
        squad/profile syncs own their attributes, not match-day payloads."""
        ids = [pp.provider_id for pp in provider_players]
        if not ids:
            return {}
        rows = (await self.db.execute(select(Player).where(Player.provider_id.in_(ids)))).scalars().all()
        players = {p.provider_id: p for p in rows}
        for pp in provider_players:
            if pp.provider_id not in players:
                players[pp.provider_id] = await self.football._sync_player(pp, team_id)
        return players

    async def sync_lineups(self, match: Match) -> bool:
        """Upsert the provider's lineups for `match`. Returns True if the
        provider supplied any (callers fingerprint the stored result to
        decide whether anything actually changed)."""
        if not self.provider.capabilities.lineups:
            return False
        provider_lineups = await self.provider.get_lineups(match.provider_id)
        if not provider_lineups:
            return False

        existing = {
            lu.team_id: lu
            for lu in (await self.db.execute(select(MatchLineup).where(MatchLineup.match_id == match.id)))
            .scalars()
            .all()
        }
        for provider_lineup in provider_lineups:
            team = await self.football._sync_team(provider_lineup.team)
            if team.id not in (match.home_team_id, match.away_team_id):
                logger.warning(
                    "Ignoring lineup for team %s: not playing in match %s", team.provider_id, match.provider_id
                )
                continue
            lineup = existing.get(team.id)
            if lineup is None:
                lineup = MatchLineup(match_id=match.id, team_id=team.id, formation=provider_lineup.formation)
                self.db.add(lineup)
                await self.db.flush()
            else:
                lineup.formation = provider_lineup.formation

            players = await self._resolve_players([e.player for e in provider_lineup.players], team.id)
            current = {
                lp.player_id: lp
                for lp in (
                    await self.db.execute(select(LineupPlayer).where(LineupPlayer.lineup_id == lineup.id))
                )
                .scalars()
                .all()
            }
            seen: set[int] = set()
            for order, entry in enumerate(provider_lineup.players):
                player = players[entry.player.provider_id]
                seen.add(player.id)
                values = {
                    "is_starter": entry.is_starter,
                    "position": entry.position or entry.player.position,
                    "shirt_number": entry.shirt_number,
                    "sort_order": order,
                }
                row = current.get(player.id)
                if row is None:
                    self.db.add(LineupPlayer(lineup_id=lineup.id, player_id=player.id, **values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
            stale = [pid for pid in current if pid not in seen]
            if stale:
                await self.db.execute(
                    delete(LineupPlayer).where(LineupPlayer.lineup_id == lineup.id, LineupPlayer.player_id.in_(stale))
                )
        await self.db.flush()
        return True

    async def sync_statistics(self, match: Match) -> bool:
        if not self.provider.capabilities.match_statistics:
            return False
        provider_stats = await self.provider.get_match_statistics(match.provider_id)
        if not provider_stats:
            return False
        existing = {
            row.team_id: row
            for row in (await self.db.execute(select(MatchStatistic).where(MatchStatistic.match_id == match.id)))
            .scalars()
            .all()
        }
        for provider_row in provider_stats:
            team = await self.football._sync_team(provider_row.team)
            if team.id not in (match.home_team_id, match.away_team_id):
                continue
            values = {field: getattr(provider_row, field) for field in _STAT_FIELDS}
            row = existing.get(team.id)
            if row is None:
                self.db.add(MatchStatistic(match_id=match.id, team_id=team.id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        await self.db.flush()
        return True

    async def sync_player_statistics(self, match: Match) -> bool:
        if not self.provider.capabilities.player_statistics:
            return False
        provider_stats = await self.provider.get_player_statistics(match.provider_id)
        if not provider_stats:
            return False
        existing = {
            row.player_id: row
            for row in (
                await self.db.execute(select(PlayerMatchStatistic).where(PlayerMatchStatistic.match_id == match.id))
            )
            .scalars()
            .all()
        }
        by_team: dict[str, list] = {}
        for provider_row in provider_stats:
            by_team.setdefault(provider_row.team.provider_id, []).append(provider_row)
        for rows in by_team.values():
            team = await self.football._sync_team(rows[0].team)
            if team.id not in (match.home_team_id, match.away_team_id):
                continue
            players = await self._resolve_players([r.player for r in rows], team.id)
            for provider_row in rows:
                player = players[provider_row.player.provider_id]
                values = {"team_id": team.id, **{f: getattr(provider_row, f) for f in _PLAYER_STAT_FIELDS}}
                row = existing.get(player.id)
                if row is None:
                    self.db.add(PlayerMatchStatistic(match_id=match.id, player_id=player.id, **values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
        await self.db.flush()
        return True

    async def sync_match_extras(self, match: Match) -> None:
        """Everything match-centre-specific for one match, in one place so
        the worker has a single call. A starting XI doesn't change once a
        match is under way (substitutions arrive as match events), so a
        live/finished match only re-syncs lineups if none are stored yet;
        a scheduled one re-syncs them (pre-kickoff changes happen).
        Statistics are re-synced on every call once the match has started."""
        if match.status == MatchStatus.SCHEDULED or not await self._has_lineups(match.id):
            await self.sync_lineups(match)
        if match.status != MatchStatus.SCHEDULED:
            await self.sync_statistics(match)
            await self.sync_player_statistics(match)

    async def _has_lineups(self, match_id: int) -> bool:
        stmt = select(MatchLineup.id).where(MatchLineup.match_id == match_id).limit(1)
        return (await self.db.execute(stmt)).first() is not None

    # -- change-detection inputs (read straight from the database) ---------------

    async def lineup_fingerprint(self, match_id: int) -> str | None:
        """Stable hash of the stored lineups, or None if none are stored.
        Changes iff a formation, a player, a starter/bench flag or a shirt
        number changed -- which is exactly when LINEUP_UPDATED should fire."""
        lineups = await self._load_lineups(match_id)
        if not lineups:
            return None
        payload = [
            (
                lu.team_id,
                lu.formation,
                [(p.player_id, p.is_starter, p.position, p.shirt_number) for p in lu.players],
            )
            for lu in sorted(lineups, key=lambda x: x.team_id)
        ]
        return hashlib.sha1(json.dumps(payload, default=str).encode(), usedforsecurity=False).hexdigest()[:16]

    async def statistics_snapshot(self, match: Match) -> dict | None:
        """Compact, JSON-serializable {home: {...}, away: {...}} of stored
        team statistics (None if nothing stored) -- diffed by change
        detection and embedded in STATISTICS_UPDATED payloads."""
        stats = await self._build_statistics(match)
        if stats.home is None and stats.away is None:
            return None
        return stats.model_dump(mode="json")

    # -- reads (database/cache -> API schemas) --------------------------------------

    async def _get_match(self, match_id: int) -> Match:
        match = (await self.db.execute(select(Match).where(Match.id == match_id))).scalar_one_or_none()
        if match is None:
            raise NotFoundError(f"Match {match_id} not found")
        return match

    async def _load_lineups(self, match_id: int) -> list[MatchLineup]:
        stmt = (
            select(MatchLineup)
            .where(MatchLineup.match_id == match_id)
            .options(
                selectinload(MatchLineup.team),
                selectinload(MatchLineup.players).selectinload(LineupPlayer.player),
            )
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def _build_lineups(self, match: Match) -> MatchLineupsOut:
        lineups = await self._load_lineups(match.id)
        if not lineups:
            return MatchLineupsOut()

        subs = (
            (
                await self.db.execute(
                    select(MatchEvent).where(
                        MatchEvent.match_id == match.id, MatchEvent.event_type == MatchEventType.SUBSTITUTION
                    )
                )
            )
            .scalars()
            .all()
        )
        # Convention (see football_service / realtime.md): substitution
        # event player = coming on, assist_player = going off.
        subbed_in = {e.player_id: e.minute for e in subs if e.player_id is not None}
        subbed_out = {e.assist_player_id: e.minute for e in subs if e.assist_player_id is not None}

        def _team_lineup(lineup: MatchLineup) -> TeamLineupOut:
            entries = [
                LineupPlayerOut(
                    player=PlayerOut.model_validate(lp.player),
                    position=lp.position,
                    shirt_number=lp.shirt_number,
                    is_starter=lp.is_starter,
                    subbed_in_minute=subbed_in.get(lp.player_id),
                    subbed_out_minute=subbed_out.get(lp.player_id),
                )
                for lp in lineup.players
            ]
            return TeamLineupOut(
                team=TeamOut.model_validate(lineup.team),
                formation=lineup.formation,
                starters=[e for e in entries if e.is_starter],
                substitutes=[e for e in entries if not e.is_starter],
            )

        by_team = {lu.team_id: lu for lu in lineups}
        home = by_team.get(match.home_team_id)
        away = by_team.get(match.away_team_id)
        return MatchLineupsOut(
            home=_team_lineup(home) if home else None,
            away=_team_lineup(away) if away else None,
        )

    async def _cached_for_match(self, match_id: int, key: str, model, build):
        """Cache-aside for match-scoped data whose TTL depends on the match's
        status. The match is only looked up on a miss (which is also where an
        unknown id becomes a 404), so a hit costs no database query."""
        ttl = {"seconds": settings.redis_default_ttl_seconds}

        async def _load():
            match = await self._get_match(match_id)
            ttl["seconds"] = cache_ttl_for_status(match.status)
            return await build(match)

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_model(key, model, _load, ttl_seconds=lambda: ttl["seconds"])

    async def get_lineups(self, match_id: int) -> MatchLineupsOut:
        return await self._cached_for_match(
            match_id, RedisKeys.match_lineups(match_id), MatchLineupsOut, self._build_lineups
        )

    async def _build_statistics(self, match: Match) -> MatchStatisticsOut:
        rows = (
            (await self.db.execute(select(MatchStatistic).where(MatchStatistic.match_id == match.id)))
            .scalars()
            .all()
        )
        by_team = {row.team_id: TeamMatchStatsOut.model_validate(row) for row in rows}
        return MatchStatisticsOut(home=by_team.get(match.home_team_id), away=by_team.get(match.away_team_id))

    async def get_statistics(self, match_id: int) -> MatchStatisticsOut:
        return await self._cached_for_match(
            match_id, RedisKeys.match_statistics(match_id), MatchStatisticsOut, self._build_statistics
        )

    async def _build_player_statistics(self, match: Match) -> MatchPlayerStatisticsOut:
        stmt = (
            select(PlayerMatchStatistic)
            .where(PlayerMatchStatistic.match_id == match.id)
            .options(selectinload(PlayerMatchStatistic.player))
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        rows = sorted(rows, key=lambda r: (r.team_id != match.home_team_id, -(r.minutes_played or 0), r.player_id))
        return MatchPlayerStatisticsOut(players=[PlayerMatchStatsOut.model_validate(r) for r in rows])

    async def get_player_statistics(self, match_id: int) -> MatchPlayerStatisticsOut:
        return await self._cached_for_match(
            match_id,
            RedisKeys.match_player_statistics(match_id),
            MatchPlayerStatisticsOut,
            self._build_player_statistics,
        )
