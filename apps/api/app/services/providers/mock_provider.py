from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.services.providers.base import FootballDataProvider
from app.services.providers.mock_data import COMPETITIONS, FIXTURES, PLAYERS, STANDINGS, TEAMS
from app.services.providers.schemas import (
    ProviderCompetition,
    ProviderMatch,
    ProviderMatchEvent,
    ProviderPlayer,
    ProviderSearchResult,
    ProviderStandingRow,
    ProviderTeam,
)


def _competition(provider_id: str) -> ProviderCompetition:
    data = COMPETITIONS[provider_id]
    return ProviderCompetition(
        provider_id=provider_id, name=data["name"], country=data["country"], type=data["type"]
    )


def _team(provider_id: str) -> ProviderTeam:
    data = TEAMS[provider_id]
    return ProviderTeam(
        provider_id=provider_id,
        name=data["name"],
        short_name=data["short_name"],
        country=data["country"],
    )


def _player(provider_id: str | None) -> ProviderPlayer | None:
    if provider_id is None:
        return None
    data = PLAYERS[provider_id]
    return ProviderPlayer(provider_id=provider_id, name=data["name"], position=data["position"])


def _kickoff_and_status(fixture: dict, now: datetime) -> tuple[datetime, str, int | None]:
    """Compute a fixture's kickoff time and status relative to `now`, so the
    mock dataset always looks live/current no matter when it's queried."""
    kind = fixture["kind"]
    today = now.date()

    if kind == "live":
        minute = fixture["minute"]
        return now - timedelta(minutes=minute), "live", minute

    if kind == "halftime":
        return now - timedelta(minutes=45), "halftime", fixture["minute"]

    if kind == "finished_today":
        kickoff = datetime.combine(today, time(hour=fixture["hour"]), tzinfo=timezone.utc)
        return kickoff, "finished", None

    if kind == "finished_yesterday":
        kickoff = datetime.combine(today - timedelta(days=1), time(hour=fixture["hour"]), tzinfo=timezone.utc)
        return kickoff, "finished", None

    if kind == "upcoming_today":
        kickoff = datetime.combine(today, time(hour=fixture["hour"]), tzinfo=timezone.utc)
        return kickoff, "scheduled", None

    if kind == "upcoming_future":
        target_day = today + timedelta(days=fixture.get("day_offset", 1))
        kickoff = datetime.combine(target_day, time(hour=fixture["hour"]), tzinfo=timezone.utc)
        return kickoff, "scheduled", None

    raise ValueError(f"Unknown fixture kind: {kind}")


def _build_match(fixture: dict, now: datetime) -> ProviderMatch:
    kickoff, status, minute = _kickoff_and_status(fixture, now)

    events = [
        ProviderMatchEvent(
            event_type=e["type"],
            minute=e["minute"],
            team=_team(fixture["home"] if e["side"] == "home" else fixture["away"]),
            player=_player(e.get("player")),
            assist_player=_player(e.get("assist")),
            description=e.get("description"),
        )
        for e in fixture.get("events", [])
    ]

    is_scheduled = status == "scheduled"
    return ProviderMatch(
        provider_id=fixture["provider_id"],
        competition=_competition(fixture["competition"]),
        home_team=_team(fixture["home"]),
        away_team=_team(fixture["away"]),
        kickoff_time=kickoff,
        status=status,
        home_score=0 if is_scheduled else fixture["home_score"],
        away_score=0 if is_scheduled else fixture["away_score"],
        venue=fixture.get("venue"),
        minute=minute,
        events=events,
    )


class MockFootballDataProvider(FootballDataProvider):
    """Deterministic in-memory provider used when no real football-data API
    is configured. Generates realistic live/today/upcoming/finished
    fixtures across six competitions from the static pool in mock_data.py;
    kickoff times are always computed relative to "now"."""

    def _all_matches(self) -> list[ProviderMatch]:
        now = datetime.now(timezone.utc)
        return [_build_match(fixture, now) for fixture in FIXTURES]

    async def get_live_matches(self) -> list[ProviderMatch]:
        return [m for m in self._all_matches() if m.status in ("live", "halftime")]

    async def get_fixtures(self, on_date: date) -> list[ProviderMatch]:
        return [m for m in self._all_matches() if m.kickoff_time.date() == on_date]

    async def get_match(self, match_id: str) -> ProviderMatch | None:
        return next((m for m in self._all_matches() if m.provider_id == match_id), None)

    async def get_competitions(self) -> list[ProviderCompetition]:
        return [_competition(competition_id) for competition_id in COMPETITIONS]

    async def get_competition_fixtures(self, competition_id: str) -> list[ProviderMatch]:
        return [m for m in self._all_matches() if m.competition.provider_id == competition_id]

    async def get_standings(self, competition_id: str) -> list[ProviderStandingRow]:
        rows = STANDINGS.get(competition_id, [])
        ranked = sorted(
            rows,
            key=lambda r: (-(r["won"] * 3 + r["drawn"]), -(r["gf"] - r["ga"])),
        )
        standings = [
            ProviderStandingRow(
                team=_team(row["team"]),
                position=position,
                played=row["played"],
                won=row["won"],
                drawn=row["drawn"],
                lost=row["lost"],
                goals_for=row["gf"],
                goals_against=row["ga"],
                points=row["won"] * 3 + row["drawn"],
            )
            for position, row in enumerate(ranked, start=1)
        ]
        return standings

    async def get_team(self, team_id: str) -> ProviderTeam | None:
        return _team(team_id) if team_id in TEAMS else None

    async def get_team_fixtures(self, team_id: str) -> list[ProviderMatch]:
        return [
            m
            for m in self._all_matches()
            if m.home_team.provider_id == team_id or m.away_team.provider_id == team_id
        ]

    async def search(self, query: str) -> ProviderSearchResult:
        q = query.strip().lower()
        if not q:
            return ProviderSearchResult()

        teams = [_team(tid) for tid, data in TEAMS.items() if q in data["name"].lower()]
        competitions = [
            _competition(cid) for cid, data in COMPETITIONS.items() if q in data["name"].lower()
        ]
        players = [
            player
            for pid, data in PLAYERS.items()
            if q in data["name"].lower() and (player := _player(pid))
        ]
        return ProviderSearchResult(teams=teams, competitions=competitions, players=players)
