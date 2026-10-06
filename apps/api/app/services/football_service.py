from __future__ import annotations

import hashlib
import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.redis_keys import RedisKeys
from app.models.competition import Competition
from app.models.enums import MatchEventType, MatchStatus
from app.models.match import Match
from app.models.match_event import MatchEvent
from app.models.player import Player
from app.models.standing import Standing
from app.models.statistics import PlayerSeasonStatistic
from app.models.team import Team
from app.schemas.competition import CompetitionOut, CompetitionSeasonsOut
from app.schemas.match import MatchDetail, MatchEventOut, MatchSummary
from app.schemas.player import PlayerOut
from app.schemas.search import SearchResults
from app.schemas.standing import StandingEntry
from app.schemas.team import TeamDetail, TeamOut
from app.services.cache import CacheAside
from app.services.pagination import paginate
from app.services.providers.base import FootballDataProvider
from app.services.providers.schemas import ProviderMatch, ProviderMatchEvent
from app.services.season import current_season_label, is_requestable_past_season
from app.services.sync_requests import request_sync_once
from app.services.upsert import upsert_by_provider_id, upsert_by_unique_fields

logger = logging.getLogger(__name__)

_MATCH_LOAD_OPTIONS = (
    selectinload(Match.competition),
    selectinload(Match.home_team),
    selectinload(Match.away_team),
)
_MATCH_DETAIL_LOAD_OPTIONS = (
    *_MATCH_LOAD_OPTIONS,
    selectinload(Match.events).selectinload(MatchEvent.team),
    selectinload(Match.events).selectinload(MatchEvent.player),
    selectinload(Match.events).selectinload(MatchEvent.assist_player),
)


class NotFoundError(Exception):
    """Raised when a requested entity does not exist. Routers translate this
    into a 404 response."""


def _synthetic_event_key(match_provider_id: str, event: ProviderMatchEvent, index: int) -> str:
    """Deterministic identity for a match event when the provider doesn't
    supply its own id (Phase 2 §25): a hash of the fields that make an
    event distinct, plus its position in the provider's event list as a
    tiebreaker (e.g. two same-minute, same-team cards with no player
    attached). The bundled mock provider always supplies its own id; this
    exists for providers that don't."""
    basis = "|".join(
        [
            match_provider_id,
            event.event_type,
            str(event.minute),
            event.team.provider_id if event.team else "",
            event.player.provider_id if event.player else "",
            str(index),
        ]
    )
    return hashlib.sha1(basis.encode()).hexdigest()[:24]


class FootballService:
    """Router-facing business logic.

    Phase 2 splits what Phase 1's methods used to do in one step:

    - **Sync** methods (provider -> database) are now only called by the
      background worker (`app/worker/tasks.py`) and the startup seed
      (`app/services/seed.py`) -- never from a request handler (spec §6).
    - **Read** methods (database/cache -> API schema) are what routers
      call via `app/api/deps.py`; they no longer call the provider
      (spec §5), with two narrow, deliberate exceptions: `search` (an
      arbitrary query has no fixed key a background job could pre-warm)
      and `list_competitions` (a small, near-static reference list that's
      cheap to cache-aside directly rather than needing its own sync job
      and DB table dependency before it can return anything).
    """

    def __init__(
        self,
        db: AsyncSession,
        provider: FootballDataProvider,
        cache: CacheAside | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.cache = cache
        # (kind, provider_id) -> (values last written, row). A bulk sync
        # mentions the same team/competition/player in dozens of payloads
        # with identical values; re-upserting each time was the dominant
        # cost of seeding. Scoped to this instance (one DB session / one
        # sync run) and only consulted when the incoming values are
        # unchanged, so it can never hide an update.
        self._synced: dict[tuple[str, str], tuple[dict, object]] = {}

    async def _upsert_memoized(self, kind: str, model, provider_id: str, values: dict):
        memo = self._synced.get((kind, provider_id))
        if memo is not None and memo[0] == values:
            return memo[1]
        obj = await upsert_by_provider_id(self.db, model, provider_id, values)
        self._synced[(kind, provider_id)] = (dict(values), obj)
        return obj

    # -- syncing (provider -> database) --------------------------------------

    async def _sync_competition(self, provider_competition) -> Competition:
        return await self._upsert_memoized(
            "competition",
            Competition,
            provider_competition.provider_id,
            {
                "name": provider_competition.name,
                "country": provider_competition.country,
                "logo_url": provider_competition.logo_url,
                "type": provider_competition.type,
            },
        )

    async def _sync_team(self, provider_team) -> Team:
        values = {
            "name": provider_team.name,
            "short_name": provider_team.short_name,
            "country": provider_team.country,
            "logo_url": provider_team.logo_url,
        }
        # Enrichment-only fields: a match payload's embedded team has no
        # venue, and must not erase one a team-level sync already stored.
        if provider_team.venue is not None:
            values["venue"] = provider_team.venue
        return await self._upsert_memoized("team", Team, provider_team.provider_id, values)

    async def _sync_player(self, provider_player, team_id: int | None, *, profile: bool = False) -> Player:
        """`profile=True` marks the row as populated by a squad/profile call
        (see `Player.profile_synced_at`). Optional attributes are only
        written when the payload actually carries them, so a thin payload
        (a match event, a search hit) never wipes out a richer one."""
        values: dict = {"name": provider_player.name}
        for field in ("position", "photo_url", "nationality", "shirt_number"):
            value = getattr(provider_player, field)
            if value is not None:
                values[field] = value
        if team_id is None and provider_player.team is not None:
            team_id = (await self._sync_team(provider_player.team)).id
        if team_id is not None:
            values["team_id"] = team_id
        if profile:
            values["profile_synced_at"] = datetime.now(timezone.utc)
            return await upsert_by_provider_id(self.db, Player, provider_player.provider_id, values)
        return await self._upsert_memoized("player", Player, provider_player.provider_id, values)

    async def sync_match(self, provider_match: ProviderMatch, *, with_events: bool = False) -> Match:
        """Upsert one match (and its competition/teams/events) from a
        provider payload. Public because `worker/tasks.py` calls this
        directly for single-match live syncs, not just full-list ones."""
        competition = await self._sync_competition(provider_match.competition)
        home = await self._sync_team(provider_match.home_team)
        away = await self._sync_team(provider_match.away_team)

        match = await upsert_by_provider_id(
            self.db,
            Match,
            provider_match.provider_id,
            {
                "competition_id": competition.id,
                "home_team_id": home.id,
                "away_team_id": away.id,
                "kickoff_time": provider_match.kickoff_time,
                "status": MatchStatus(provider_match.status),
                "home_score": provider_match.home_score,
                "away_score": provider_match.away_score,
                "half_time_home_score": provider_match.half_time_home_score,
                "half_time_away_score": provider_match.half_time_away_score,
                "venue": provider_match.venue,
                "minute": provider_match.minute,
                "last_synced_at": datetime.now(timezone.utc),
            },
        )

        if with_events:
            await self._sync_match_events(match, provider_match)

        return match

    async def _sync_match_events(self, match: Match, provider_match: ProviderMatch) -> None:
        """Upserts events by their (match_id, provider_id) identity instead
        of Phase 1's delete-all-then-reinsert, so an event's database id
        stays stable across polls (spec §24/§25) -- change detection relies
        on that stability to tell "still the same event" apart from "new
        event". Events no longer present in the provider's payload (rare --
        a provider correction) are removed."""
        seen_keys: set[str] = set()
        for index, provider_event in enumerate(provider_match.events):
            team = await self._sync_team(provider_event.team) if provider_event.team else None
            player = (
                await self._sync_player(provider_event.player, team.id if team else None)
                if provider_event.player
                else None
            )
            assist = (
                await self._sync_player(provider_event.assist_player, team.id if team else None)
                if provider_event.assist_player
                else None
            )
            try:
                event_type = MatchEventType(provider_event.event_type)
            except ValueError:
                logger.warning(
                    "Skipping match event with unsupported type %r on match %s",
                    provider_event.event_type,
                    provider_match.provider_id,
                )
                continue
            event_key = provider_event.provider_id or _synthetic_event_key(
                provider_match.provider_id, provider_event, index
            )
            seen_keys.add(event_key)
            await upsert_by_unique_fields(
                self.db,
                MatchEvent,
                {"match_id": match.id, "provider_id": event_key},
                {
                    "event_type": event_type,
                    "minute": provider_event.minute,
                    "extra_minute": provider_event.extra_minute,
                    "team_id": team.id if team else None,
                    "player_id": player.id if player else None,
                    "assist_player_id": assist.id if assist else None,
                    "description": provider_event.description,
                    "event_detail": provider_event.event_detail,
                },
            )

        stale_condition = (
            MatchEvent.provider_id.notin_(seen_keys) if seen_keys else MatchEvent.provider_id.isnot(None)
        )
        await self.db.execute(
            delete(MatchEvent).where(
                MatchEvent.match_id == match.id,
                or_(MatchEvent.provider_id.is_(None), stale_condition),
            )
        )
        await self.db.flush()

    async def sync_standings(self, competition: Competition, season: str | None = None) -> None:
        """Persist a competition's table. Standings are no longer fetched
        live on every request (see `get_standings` below) -- the worker calls
        this alongside fixture syncing. `season` (Phase 5) syncs a *past*
        season through the provider's historical method instead."""
        if season is None:
            provider_rows = await self.provider.get_standings(competition.provider_id)
        else:
            provider_rows = await self.provider.get_historical_standings(competition.provider_id, season)
        default_season = season or current_season_label()
        for row in provider_rows:
            team = await self._sync_team(row.team)
            await upsert_by_unique_fields(
                self.db,
                Standing,
                {
                    "competition_id": competition.id,
                    "season": row.season or default_season,
                    "group_name": row.group or "",
                    "team_id": team.id,
                },
                {
                    "position": row.position,
                    "played": row.played,
                    "won": row.won,
                    "drawn": row.drawn,
                    "lost": row.lost,
                    "goals_for": row.goals_for,
                    "goals_against": row.goals_against,
                    "points": row.points,
                    "description": row.description,
                    "form": row.form,
                },
            )

    async def sync_all_competitions_and_fixtures(self) -> None:
        """Pull every competition, its current fixtures, and its standings
        from the provider into the database. Used on app startup so
        id-based lookups work immediately, without waiting for a background
        sync cycle to populate the database first."""
        for provider_competition in await self.provider.get_competitions():
            competition = await self._sync_competition(provider_competition)
            fixtures = await self.provider.get_competition_fixtures(provider_competition.provider_id)
            for provider_match in fixtures:
                await self.sync_match(provider_match, with_events=True)
            await self.sync_standings(competition)
            if self.provider.capabilities.top_scorers:
                from app.services.team_player_service import TeamPlayerService

                await TeamPlayerService(self.db, self.provider, self).sync_top_scorers(competition)
        await self.db.commit()

    # -- reads (database/cache -> API schemas) -------------------------------

    async def _load_match(self, match_id: int, *, with_events: bool) -> Match | None:
        options = _MATCH_DETAIL_LOAD_OPTIONS if with_events else _MATCH_LOAD_OPTIONS
        stmt = select(Match).where(Match.id == match_id).options(*options)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _query_matches(self, *conditions, descending: bool = False) -> list[MatchSummary]:
        stmt = (
            select(Match)
            .where(*conditions)
            .options(*_MATCH_LOAD_OPTIONS)
            .order_by(Match.kickoff_time.desc() if descending else Match.kickoff_time)
        )
        matches = (await self.db.execute(stmt)).scalars().all()
        return [MatchSummary.model_validate(m) for m in matches]

    async def get_live_matches(self) -> list[MatchSummary]:
        async def _load() -> list[MatchSummary]:
            return await self._query_matches(Match.status.in_([MatchStatus.LIVE, MatchStatus.HALFTIME]))

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_list(
            RedisKeys.LIVE_MATCHES, MatchSummary, _load, ttl_seconds=settings.redis_live_match_ttl_seconds
        )

    async def get_today_matches(self) -> list[MatchSummary]:
        async def _load() -> list[MatchSummary]:
            today = datetime.now(timezone.utc).date()
            start = datetime.combine(today, time.min, tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            return await self._query_matches(Match.kickoff_time >= start, Match.kickoff_time < end)

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_list(
            RedisKeys.TODAY_MATCHES, MatchSummary, _load, ttl_seconds=settings.redis_default_ttl_seconds
        )

    async def get_upcoming_matches(self, days: int = 7) -> list[MatchSummary]:
        async def _load() -> list[MatchSummary]:
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=days)
            return await self._query_matches(
                Match.status == MatchStatus.SCHEDULED,
                Match.kickoff_time > now,
                Match.kickoff_time <= end,
            )

        if self.cache is None:
            return await _load()
        key = RedisKeys.upcoming_matches(datetime.now(timezone.utc).date())
        return await self.cache.get_or_set_list(
            key, MatchSummary, _load, ttl_seconds=settings.redis_default_ttl_seconds
        )

    async def get_match(self, match_id: int) -> MatchDetail:
        async def _load() -> MatchDetail:
            match = await self._load_match(match_id, with_events=True)
            if match is None:
                raise NotFoundError(f"Match {match_id} not found")
            return MatchDetail.model_validate(match)

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_model(
            RedisKeys.match(match_id), MatchDetail, _load, ttl_seconds=settings.redis_live_match_ttl_seconds
        )

    async def get_match_events(self, match_id: int) -> list[MatchEventOut]:
        # Piggybacks on the match-detail cache entry above rather than
        # maintaining a second `football:match:{id}:events` entry with its
        # own TTL -- detail and events are always synced together, so a
        # duplicate cache read would only ever return the same data.
        detail = await self.get_match(match_id)
        return detail.events

    # -- competitions ---------------------------------------------------

    async def list_competitions(self, page: int, page_size: int) -> tuple[list[CompetitionOut], int]:
        async def _load() -> list[CompetitionOut]:
            provider_competitions = await self.provider.get_competitions()
            competitions = [await self._sync_competition(pc) for pc in provider_competitions]
            await self.db.commit()
            competitions.sort(key=lambda c: c.name)
            return [CompetitionOut.model_validate(c) for c in competitions]

        if self.cache is None:
            all_competitions = await _load()
        else:
            all_competitions = await self.cache.get_or_set_list(
                "football:competitions",
                CompetitionOut,
                _load,
                ttl_seconds=settings.redis_default_ttl_seconds,
            )
        return paginate(all_competitions, page, page_size)

    async def _get_competition_by_id(self, competition_id: int) -> Competition:
        result = await self.db.execute(select(Competition).where(Competition.id == competition_id))
        competition = result.scalar_one_or_none()
        if competition is None:
            raise NotFoundError(f"Competition {competition_id} not found")
        return competition

    async def get_competition(self, competition_id: int) -> CompetitionOut:
        competition = await self._get_competition_by_id(competition_id)
        return CompetitionOut.model_validate(competition)

    async def get_competition_fixtures(
        self, competition_id: int, page: int, page_size: int, *, scope: str = "all"
    ) -> tuple[list[MatchSummary], int]:
        """`scope`: "all" (every stored match, oldest first -- the Phase 1
        behaviour), "upcoming" (scheduled/live/halftime, soonest first) or
        "results" (finished, most recent first)."""
        competition = await self._get_competition_by_id(competition_id)

        async def _load() -> list[MatchSummary]:
            return await self._query_matches(Match.competition_id == competition.id)

        if self.cache is None:
            summaries = await _load()
        else:
            key = RedisKeys.competition_fixtures(competition_id, datetime.now(timezone.utc).date())
            summaries = await self.cache.get_or_set_list(
                key, MatchSummary, _load, ttl_seconds=settings.redis_default_ttl_seconds
            )
        if scope == "upcoming":
            summaries = [m for m in summaries if m.status in ("scheduled", "live", "halftime")]
        elif scope == "results":
            summaries = [m for m in reversed(summaries) if m.status == "finished"]
        return paginate(summaries, page, page_size)

    async def _latest_season(self, competition_id: int) -> str | None:
        stmt = select(func.max(Standing.season)).where(Standing.competition_id == competition_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_standings(
        self, competition_id: int, season: str | None = None, group: str | None = None
    ) -> list[StandingEntry]:
        """The table for `season` (default: the latest stored one), ordered
        by group then position. `group` narrows a group-stage competition
        to one group; it is applied after the cache read so all groups of a
        season share one cache entry."""
        competition = await self._get_competition_by_id(competition_id)

        async def _load() -> list[StandingEntry]:
            resolved = season or await self._latest_season(competition.id)
            if resolved is None:
                return []
            stmt = (
                select(Standing)
                .where(Standing.competition_id == competition.id, Standing.season == resolved)
                .options(selectinload(Standing.team))
                .order_by(Standing.group_name, Standing.position)
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            if not rows and season is not None:
                await self.request_season_sync(competition, season)
            return [StandingEntry.model_validate(row) for row in rows]

        if self.cache is None:
            entries = await _load()
        else:
            key = RedisKeys.competition_standings(competition_id, season)
            entries = await self.cache.get_or_set_list(
                key, StandingEntry, _load, ttl_seconds=settings.redis_default_ttl_seconds
            )
        if group is not None:
            entries = [e for e in entries if e.group_name == group]
        return entries

    async def request_season_sync(self, competition: Competition, season: str) -> bool:
        """A client asked for a season we haven't stored. If the provider can
        supply past seasons and the label is sane, queue a one-off background
        sync (debounced + budgeted like every on-demand sync); the answer for
        now is empty and the client re-checks."""
        if not self.provider.capabilities.historical_seasons or not is_requestable_past_season(season):
            return False
        from app.services.team_player_service import _enqueue_season_sync

        return await request_sync_once(
            self.cache,
            "season",
            f"{competition.id}:{season}",
            lambda: _enqueue_season_sync(competition.id, season),
        )

    async def get_competition_seasons(self, competition_id: int) -> CompetitionSeasonsOut:
        async def _load() -> CompetitionSeasonsOut:
            await self._get_competition_by_id(competition_id)  # only on a cache miss; also the 404
            standing_seasons = select(Standing.season).where(Standing.competition_id == competition_id)
            scorer_seasons = select(PlayerSeasonStatistic.season).where(
                PlayerSeasonStatistic.competition_id == competition_id
            )
            rows = (await self.db.execute(standing_seasons.union(scorer_seasons))).scalars().all()
            seasons = sorted(set(rows), reverse=True)
            return CompetitionSeasonsOut(
                current=seasons[0] if seasons else None,
                seasons=seasons,
                historical_supported=self.provider.capabilities.historical_seasons,
            )

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_model(
            RedisKeys.competition_seasons(competition_id),
            CompetitionSeasonsOut,
            _load,
            ttl_seconds=settings.redis_default_ttl_seconds,
        )

    # -- teams ------------------------------------------------------------

    async def _get_team_by_id(self, team_id: int) -> Team:
        result = await self.db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one_or_none()
        if team is None:
            raise NotFoundError(f"Team {team_id} not found")
        return team

    async def get_team(self, team_id: int) -> TeamDetail:
        async def _load() -> TeamDetail:
            team = await self._get_team_by_id(team_id)  # only on a cache miss; also the 404
            stmt = (
                select(Competition)
                .join(Standing, Standing.competition_id == Competition.id)
                .where(Standing.team_id == team.id)
                .distinct()
                .order_by(Competition.name)
            )
            competitions = (await self.db.execute(stmt)).scalars().all()
            detail = TeamDetail.model_validate(team)
            detail.competitions = [CompetitionOut.model_validate(c) for c in competitions]
            return detail

        if self.cache is None:
            return await _load()
        return await self.cache.get_or_set_model(
            RedisKeys.team(team_id), TeamDetail, _load, ttl_seconds=settings.redis_default_ttl_seconds
        )

    async def get_team_fixtures(
        self, team_id: int, page: int, page_size: int, *, upcoming_only: bool = False
    ) -> tuple[list[MatchSummary], int]:
        team = await self._get_team_by_id(team_id)

        async def _load() -> list[MatchSummary]:
            return await self._query_matches(or_(Match.home_team_id == team.id, Match.away_team_id == team.id))

        if self.cache is None:
            all_matches = await _load()
        else:
            key = RedisKeys.team_fixtures(team_id)
            all_matches = await self.cache.get_or_set_list(
                key, MatchSummary, _load, ttl_seconds=settings.redis_default_ttl_seconds
            )

        if upcoming_only:
            filtered = [m for m in all_matches if m.status == "scheduled"]
        else:
            # Results read newest-first (the cached list is oldest-first).
            filtered = [m for m in reversed(all_matches) if m.status == "finished"]
        return paginate(filtered, page, page_size)

    # -- search -------------------------------------------------------------

    async def search(self, query: str) -> SearchResults:
        # Deliberately not cached/background-synced: an arbitrary query
        # string has no fixed cache key a sync job could pre-warm, and
        # search is inherently interactive (spec §4's cache list doesn't
        # include it).
        query = query.strip()
        if not query:
            return SearchResults()

        local = await self._search_database(query)
        if local.teams or local.competitions or local.players or local.matches:
            return local

        # Nothing stored matches: ask the provider (it may know entities
        # the background syncs haven't reached yet).
        results = await self.provider.search(query)

        teams = [await self._sync_team(t) for t in results.teams]
        competitions = [await self._sync_competition(c) for c in results.competitions]
        players = [await self._sync_player(p, team_id=None) for p in results.players]
        await self.db.commit()

        return SearchResults(
            teams=[TeamOut.model_validate(t) for t in teams],
            competitions=[CompetitionOut.model_validate(c) for c in competitions],
            players=[PlayerOut.model_validate(p) for p in players],
        )

    async def _search_database(self, query: str, limit: int = 10) -> SearchResults:
        """Phase 4 §24: search what is already stored, using the trigram
        indexes on the name columns (`ILIKE '%q%'` is index-assisted for
        3+ character queries) and the team-id indexes for matches -- every
        query is LIMITed, nothing scans a table unbounded."""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"

        teams = (
            (await self.db.execute(select(Team).where(Team.name.ilike(pattern, escape="\\")).order_by(Team.name).limit(limit)))
            .scalars()
            .all()
        )
        competitions = (
            (
                await self.db.execute(
                    select(Competition).where(Competition.name.ilike(pattern, escape="\\")).order_by(Competition.name).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        players = (
            (await self.db.execute(select(Player).where(Player.name.ilike(pattern, escape="\\")).order_by(Player.name).limit(limit)))
            .scalars()
            .all()
        )

        matches: list[Match] = []
        if teams:
            ids = [t.id for t in teams]
            stmt = (
                select(Match)
                .where(or_(Match.home_team_id.in_(ids), Match.away_team_id.in_(ids)))
                .options(*_MATCH_LOAD_OPTIONS)
                # Nearest to "now" first: live/imminent/just-finished matches
                # before months-old history.
                .order_by(func.abs(func.extract("epoch", Match.kickoff_time - func.now())))
                .limit(limit)
            )
            matches = list((await self.db.execute(stmt)).scalars().all())

        return SearchResults(
            teams=[TeamOut.model_validate(t) for t in teams],
            competitions=[CompetitionOut.model_validate(c) for c in competitions],
            players=[PlayerOut.model_validate(p) for p in players],
            matches=[MatchSummary.model_validate(m) for m in matches],
        )
