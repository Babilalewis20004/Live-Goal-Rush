from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.competition import Competition
from app.models.enums import MatchEventType, MatchStatus
from app.models.match import Match
from app.models.match_event import MatchEvent
from app.models.player import Player
from app.models.team import Team
from app.schemas.competition import CompetitionOut
from app.schemas.match import MatchDetail, MatchSummary
from app.schemas.player import PlayerOut
from app.schemas.search import SearchResults
from app.schemas.standing import StandingEntry
from app.schemas.team import TeamOut
from app.services.pagination import paginate
from app.services.providers.base import FootballDataProvider
from app.services.providers.schemas import ProviderMatch
from app.services.upsert import upsert_by_provider_id

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


class FootballService:
    """Router-facing business logic. Syncs provider data into Postgres on
    read (Phase 1 has no background ingestion job yet) and always returns
    data shaped from the database, never raw provider payloads."""

    def __init__(self, db: AsyncSession, provider: FootballDataProvider) -> None:
        self.db = db
        self.provider = provider

    # -- syncing (provider -> database) ------------------------------------

    async def _sync_competition(self, provider_competition) -> Competition:
        return await upsert_by_provider_id(
            self.db,
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
        return await upsert_by_provider_id(
            self.db,
            Team,
            provider_team.provider_id,
            {
                "name": provider_team.name,
                "short_name": provider_team.short_name,
                "country": provider_team.country,
                "logo_url": provider_team.logo_url,
            },
        )

    async def _sync_player(self, provider_player, team_id: int | None) -> Player:
        return await upsert_by_provider_id(
            self.db,
            Player,
            provider_player.provider_id,
            {
                "name": provider_player.name,
                "position": provider_player.position,
                "photo_url": provider_player.photo_url,
                "team_id": team_id,
            },
        )

    async def _sync_match(self, provider_match: ProviderMatch, *, with_events: bool = False) -> Match:
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
            },
        )

        if with_events:
            await self.db.execute(delete(MatchEvent).where(MatchEvent.match_id == match.id))
            for provider_event in provider_match.events:
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
                self.db.add(
                    MatchEvent(
                        provider_id=provider_event.provider_id,
                        match_id=match.id,
                        event_type=MatchEventType(provider_event.event_type),
                        minute=provider_event.minute,
                        extra_minute=provider_event.extra_minute,
                        team_id=team.id if team else None,
                        player_id=player.id if player else None,
                        assist_player_id=assist.id if assist else None,
                        description=provider_event.description,
                    )
                )
            await self.db.flush()

        return match

    # -- reads (database -> API schemas) -----------------------------------

    async def _load_match(self, match_id: int, *, with_events: bool) -> Match | None:
        options = _MATCH_DETAIL_LOAD_OPTIONS if with_events else _MATCH_LOAD_OPTIONS
        stmt = select(Match).where(Match.id == match_id).options(*options)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _sync_and_load(self, provider_matches: list[ProviderMatch]) -> list[MatchSummary]:
        matches = [await self._sync_match(pm) for pm in provider_matches]
        await self.db.commit()
        matches.sort(key=lambda m: m.kickoff_time)
        loaded = [await self._load_match(m.id, with_events=False) for m in matches]
        return [MatchSummary.model_validate(m) for m in loaded if m is not None]

    async def get_live_matches(self) -> list[MatchSummary]:
        provider_matches = await self.provider.get_live_matches()
        return await self._sync_and_load(provider_matches)

    async def get_today_matches(self) -> list[MatchSummary]:
        today = datetime.now(timezone.utc).date()
        provider_matches = await self.provider.get_fixtures(today)
        return await self._sync_and_load(provider_matches)

    async def get_upcoming_matches(self, days: int = 7) -> list[MatchSummary]:
        now = datetime.now(timezone.utc)
        today = now.date()
        provider_matches: list[ProviderMatch] = []
        seen_ids: set[str] = set()
        for offset in range(days + 1):
            for pm in await self.provider.get_fixtures(today + timedelta(days=offset)):
                if pm.status == "scheduled" and pm.kickoff_time > now and pm.provider_id not in seen_ids:
                    provider_matches.append(pm)
                    seen_ids.add(pm.provider_id)
        return await self._sync_and_load(provider_matches)

    async def get_match(self, match_id: int) -> MatchDetail:
        match = await self._load_match(match_id, with_events=False)
        if match is None:
            raise NotFoundError(f"Match {match_id} not found")

        provider_match = await self.provider.get_match(match.provider_id)
        if provider_match is not None:
            match = await self._sync_match(provider_match, with_events=True)
            await self.db.commit()

        match = await self._load_match(match.id, with_events=True)
        if match is None:
            raise NotFoundError(f"Match {match_id} not found")
        return MatchDetail.model_validate(match)

    async def get_match_events(self, match_id: int) -> list:
        detail = await self.get_match(match_id)
        return detail.events

    async def sync_all_competitions_and_fixtures(self) -> None:
        """Pull every competition and its current fixtures from the provider
        into the database. Used on app startup so id-based lookups work
        immediately, without waiting for a prior list request to populate
        the database first."""
        for provider_competition in await self.provider.get_competitions():
            await self._sync_competition(provider_competition)
            fixtures = await self.provider.get_competition_fixtures(provider_competition.provider_id)
            for provider_match in fixtures:
                await self._sync_match(provider_match, with_events=True)
        await self.db.commit()

    # -- competitions ---------------------------------------------------

    async def list_competitions(self, page: int, page_size: int) -> tuple[list[CompetitionOut], int]:
        provider_competitions = await self.provider.get_competitions()
        competitions = [await self._sync_competition(pc) for pc in provider_competitions]
        await self.db.commit()
        competitions.sort(key=lambda c: c.name)
        items, total = paginate(competitions, page, page_size)
        return [CompetitionOut.model_validate(c) for c in items], total

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
        self, competition_id: int, page: int, page_size: int
    ) -> tuple[list[MatchSummary], int]:
        competition = await self._get_competition_by_id(competition_id)
        provider_matches = await self.provider.get_competition_fixtures(competition.provider_id)
        summaries = await self._sync_and_load(provider_matches)
        items, total = paginate(summaries, page, page_size)
        return items, total

    async def get_standings(self, competition_id: int) -> list[StandingEntry]:
        competition = await self._get_competition_by_id(competition_id)
        provider_rows = await self.provider.get_standings(competition.provider_id)
        entries = []
        for row in provider_rows:
            team = await self._sync_team(row.team)
            entries.append(
                StandingEntry(
                    position=row.position,
                    team=TeamOut.model_validate(team),
                    played=row.played,
                    won=row.won,
                    drawn=row.drawn,
                    lost=row.lost,
                    goals_for=row.goals_for,
                    goals_against=row.goals_against,
                    points=row.points,
                )
            )
        await self.db.commit()
        return entries

    # -- teams ------------------------------------------------------------

    async def _get_team_by_id(self, team_id: int) -> Team:
        result = await self.db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one_or_none()
        if team is None:
            raise NotFoundError(f"Team {team_id} not found")
        return team

    async def get_team(self, team_id: int) -> TeamOut:
        team = await self._get_team_by_id(team_id)
        return TeamOut.model_validate(team)

    async def get_team_fixtures(
        self, team_id: int, page: int, page_size: int, *, upcoming_only: bool = False
    ) -> tuple[list[MatchSummary], int]:
        team = await self._get_team_by_id(team_id)
        provider_matches = await self.provider.get_team_fixtures(team.provider_id)
        if upcoming_only:
            provider_matches = [m for m in provider_matches if m.status == "scheduled"]
        else:
            provider_matches = [m for m in provider_matches if m.status == "finished"]
        summaries = await self._sync_and_load(provider_matches)
        items, total = paginate(summaries, page, page_size)
        return items, total

    # -- search -------------------------------------------------------------

    async def search(self, query: str) -> SearchResults:
        query = query.strip()
        if not query:
            return SearchResults()

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
