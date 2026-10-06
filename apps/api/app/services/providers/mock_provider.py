from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.core.config import settings
from app.services.providers import mock_extras
from app.services.providers.base import FootballDataProvider
from app.services.providers.mock_data import COMPETITIONS, FIXTURES, PLAYERS, STANDINGS, TEAMS
from app.services.providers.schemas import (
    ProviderCapabilities,
    ProviderCompetition,
    ProviderLineup,
    ProviderLineupPlayer,
    ProviderMatch,
    ProviderMatchEvent,
    ProviderPlayer,
    ProviderPlayerMatchStatistics,
    ProviderSearchResult,
    ProviderStandingRow,
    ProviderTeam,
    ProviderTeamMatchStatistics,
    ProviderTopScorer,
)
from app.services.season import current_season_label

# Phase 2: a "live"/"halftime" fixture's minute, score and revealed events
# now progress deterministically from this process's start time, instead of
# being frozen at whatever mock_data.py hard-codes. This is what makes the
# real-time pipeline (adaptive polling -> change detection -> pub/sub ->
# WebSocket) observably do something end-to-end with the bundled mock
# provider: run the stack and wait, and a live match's minute/score/events
# actually change between polls, on a repeating ~100-simulated-minute cycle
# (first half, a short break, second half, full time, then kicks off again)
# so a demo session never runs out of things to observe. Real-world minute
# 45 = FIRST_HALF_END simulated minutes elapsed; HALFTIME_BREAK simulated
# minutes of "halftime" follow; the second half then runs for another
# FIRST_HALF_END simulated minutes (mapped onto match-minutes 45-90); then
# FULL_TIME_PAUSE simulated minutes of "finished" before the next kickoff.
_PROCESS_START = datetime.now(timezone.utc)
_FIRST_HALF_END = 45
_HALFTIME_BREAK = 5
_FULL_TIME_PAUSE = 5
_CYCLE_LENGTH = _FIRST_HALF_END + _HALFTIME_BREAK + _FIRST_HALF_END + _FULL_TIME_PAUSE

_GOAL_EVENT_TYPES = {"goal", "penalty"}


def _elapsed_sim_minutes(now: datetime) -> float:
    elapsed_seconds = (now - _PROCESS_START).total_seconds()
    return elapsed_seconds / max(settings.mock_live_seconds_per_minute, 0.01)


def _cycle_phase(base_minute: int, now: datetime) -> tuple[str, int]:
    """Maps a fixture's declared starting minute plus elapsed sim time onto
    (status, displayed match-minute) for the current point in its repeating
    lifecycle cycle."""
    t = (base_minute + _elapsed_sim_minutes(now)) % _CYCLE_LENGTH

    if t < _FIRST_HALF_END:
        return "live", int(t)

    t -= _FIRST_HALF_END
    if t < _HALFTIME_BREAK:
        return "halftime", _FIRST_HALF_END

    t -= _HALFTIME_BREAK
    if t < _FIRST_HALF_END:
        return "live", _FIRST_HALF_END + int(t)

    return "finished", _FIRST_HALF_END + _FIRST_HALF_END


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
        venue=mock_extras.TEAM_VENUES.get(provider_id),
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

    if kind in ("live", "halftime"):
        status, minute = _cycle_phase(fixture["minute"], now)
        return now - timedelta(minutes=minute), status, (None if status == "finished" else minute)

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

    if kind == "history":
        target_day = today - timedelta(days=fixture["days_ago"])
        kickoff = datetime.combine(target_day, time(hour=fixture["hour"]), tzinfo=timezone.utc)
        return kickoff, "finished", None

    raise ValueError(f"Unknown fixture kind: {kind}")


def _revealed_events(fixture: dict, elapsed_minute: int | None) -> list[dict]:
    """Events whose minute has been "reached" by the simulated match clock.
    For non-live fixtures (finished/upcoming), elapsed_minute is None and
    all authored events are already final, so everything is revealed."""
    all_events = fixture.get("events", [])
    if elapsed_minute is None:
        return all_events
    return [e for e in all_events if e["minute"] <= elapsed_minute]


def _score_from_events(fixture: dict, revealed: list[dict]) -> tuple[int, int]:
    """For live/halftime fixtures, the score is derived from revealed goal
    events rather than trusted from the fixture's static home_score/
    away_score -- that's what makes the score change in lockstep with the
    minute as the simulated clock advances, instead of jumping straight to
    the final score. Other fixture kinds keep their authored final score."""
    if fixture["kind"] not in ("live", "halftime"):
        return fixture["home_score"], fixture["away_score"]

    home = sum(1 for e in revealed if e["type"] in _GOAL_EVENT_TYPES and e["side"] == "home")
    away = sum(1 for e in revealed if e["type"] in _GOAL_EVENT_TYPES and e["side"] == "away")
    return home, away


def _player_from_dict(data: dict, team_id: str | None = None) -> ProviderPlayer:
    return ProviderPlayer(
        provider_id=data["provider_id"],
        name=data["name"],
        position=data["position"],
        nationality=data.get("nationality"),
        shirt_number=data.get("shirt_number"),
        team=_team(team_id) if team_id else None,
    )


def _fixture_progress(fixture: dict, now: datetime) -> tuple[str, int | None, list[dict], float]:
    """(status, minute, revealed events, fraction of the match played) for a
    fixture right now -- the shared basis for the match, lineup and
    statistics builders, so they can never disagree with each other."""
    _, status, minute = _kickoff_and_status(fixture, now)
    if status == "scheduled":
        return status, minute, [], 0.0
    elapsed = minute if status != "finished" else _FIRST_HALF_END * 2
    revealed = _revealed_events(fixture, elapsed)
    fraction = 1.0 if status == "finished" else min((minute or 0) / (_FIRST_HALF_END * 2), 1.0)
    return status, minute, revealed, fraction


def _build_match(fixture: dict, now: datetime) -> ProviderMatch:
    kickoff, status, minute = _kickoff_and_status(fixture, now)
    revealed = _revealed_events(fixture, minute if status != "finished" else _FIRST_HALF_END * 2)
    home_score, away_score = _score_from_events(fixture, revealed)

    events = [
        ProviderMatchEvent(
            provider_id=f"{fixture['provider_id']}-ev-{index}",
            event_type=e["type"],
            minute=e["minute"],
            team=_team(fixture["home"] if e["side"] == "home" else fixture["away"]),
            player=_player(e.get("player")),
            assist_player=_player(e.get("assist")),
            description=e.get("description"),
        )
        for index, e in enumerate(fixture.get("events", []))
        if e in revealed
    ]

    is_scheduled = status == "scheduled"
    return ProviderMatch(
        provider_id=fixture["provider_id"],
        competition=_competition(fixture["competition"]),
        home_team=_team(fixture["home"]),
        away_team=_team(fixture["away"]),
        kickoff_time=kickoff,
        status=status,
        home_score=0 if is_scheduled else home_score,
        away_score=0 if is_scheduled else away_score,
        venue=fixture.get("venue"),
        minute=minute,
        events=events,
    )


_HISTORY_CACHE: list[dict] | None = None


def _history() -> list[dict]:
    """Generated once per process -- days-ago offsets are fixed, kickoff
    dates are resolved against "now" in `_kickoff_and_status`."""
    global _HISTORY_CACHE
    if _HISTORY_CACHE is None:
        _HISTORY_CACHE = mock_extras.history_fixtures()
    return _HISTORY_CACHE


class MockFootballDataProvider(FootballDataProvider):
    """Deterministic in-memory provider used when no real football-data API
    is configured. Generates realistic live/today/upcoming/finished
    fixtures across six competitions from the static pool in mock_data.py;
    kickoff times are always computed relative to "now", and "live"/
    "halftime" fixtures additionally progress in real time (see the module
    docstring above)."""

    def _all_matches(self) -> list[ProviderMatch]:
        now = datetime.now(timezone.utc)
        return [_build_match(fixture, now) for fixture in (*FIXTURES, *_history())]

    def _fixture(self, match_id: str) -> dict | None:
        return next((f for f in (*FIXTURES, *_history()) if f["provider_id"] == match_id), None)

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
                season=current_season_label(),
                description=mock_extras.standing_description(competition_id, position, len(ranked)),
                form=mock_extras.standing_form(
                    competition_id, row["team"], row["won"], row["drawn"], row["played"]
                ),
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

    # -- Phase 4 ---------------------------------------------------------------

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            match_events=True,
            lineups=True,
            match_statistics=True,
            player_statistics=True,
            team_squads=True,
            player_profiles=True,
            standings=True,
            top_scorers=True,
            venues=True,
            historical_seasons=True,
        )

    async def get_lineups(self, match_id: str) -> list[ProviderLineup]:
        fixture = self._fixture(match_id)
        if fixture is None or fixture["kind"] == "history":
            return []
        status, _, _, _ = _fixture_progress(fixture, datetime.now(timezone.utc))
        if status == "scheduled":
            return []  # lineups are published around kickoff, not before
        lineups: list[ProviderLineup] = []
        for side in ("home", "away"):
            data = mock_extras.build_lineup(fixture, side)
            players = [
                ProviderLineupPlayer(
                    player=_player_from_dict(pl),
                    is_starter=is_starter,
                    position=pl["position"],
                    shirt_number=pl["shirt_number"],
                )
                for is_starter, group in ((True, data["starters"]), (False, data["bench"]))
                for pl in group
            ]
            lineups.append(
                ProviderLineup(team=_team(data["team_id"]), formation=data["formation"], players=players)
            )
        return lineups

    async def get_match_statistics(self, match_id: str) -> list[ProviderTeamMatchStatistics]:
        fixture = self._fixture(match_id)
        if fixture is None or fixture["kind"] == "history":
            return []
        status, _, revealed, fraction = _fixture_progress(fixture, datetime.now(timezone.utc))
        if status == "scheduled":
            return []
        return [
            ProviderTeamMatchStatistics(
                team=_team(fixture["home"] if side == "home" else fixture["away"]),
                **mock_extras.team_statistics(fixture, side, fraction, revealed),
            )
            for side in ("home", "away")
        ]

    async def get_player_statistics(self, match_id: str) -> list[ProviderPlayerMatchStatistics]:
        fixture = self._fixture(match_id)
        if fixture is None or fixture["kind"] == "history":
            return []
        status, _, revealed, fraction = _fixture_progress(fixture, datetime.now(timezone.utc))
        if status == "scheduled":
            return []
        result: list[ProviderPlayerMatchStatistics] = []
        for side in ("home", "away"):
            team = _team(fixture["home"] if side == "home" else fixture["away"])
            for row in mock_extras.player_statistics(fixture, side, fraction, revealed):
                stats = {k: v for k, v in row.items() if k != "player"}
                result.append(
                    ProviderPlayerMatchStatistics(player=_player_from_dict(row["player"]), team=team, **stats)
                )
        return result

    async def get_team_squad(self, team_id: str) -> list[ProviderPlayer]:
        if team_id not in TEAMS:
            return []
        return [_player_from_dict(pl, team_id) for pl in mock_extras.build_squad(team_id)]

    async def get_player(self, player_id: str) -> ProviderPlayer | None:
        entry = mock_extras.player_index().get(player_id)
        if entry is None:
            return None
        player, team_id = entry
        return _player_from_dict(player, team_id)

    async def get_top_scorers(self, competition_id: str) -> list[ProviderTopScorer]:
        index = mock_extras.player_index()
        return [
            ProviderTopScorer(
                player=_player_from_dict(index[row["player_id"]][0], row["team_id"]),
                team=_team(row["team_id"]),
                season=current_season_label(),
                goals=row["goals"],
                assists=row["assists"],
                appearances=row["appearances"],
                penalties=row["penalties"],
            )
            for row in mock_extras.top_scorers(competition_id)
            if row["player_id"] in index
        ]

    async def get_historical_standings(self, competition_id: str, season: str) -> list[ProviderStandingRow]:
        rows = mock_extras.historical_table(competition_id, season)
        return [
            ProviderStandingRow(
                team=_team(row["team"]),
                season=season,
                description=mock_extras.standing_description(competition_id, position, len(rows)),
                form=None,  # form is only meaningful for the current season
                position=position,
                played=row["played"],
                won=row["won"],
                drawn=row["drawn"],
                lost=row["lost"],
                goals_for=row["gf"],
                goals_against=row["ga"],
                points=row["won"] * 3 + row["drawn"],
            )
            for position, row in enumerate(rows, start=1)
        ]

    async def get_historical_top_scorers(self, competition_id: str, season: str) -> list[ProviderTopScorer]:
        index = mock_extras.player_index()
        return [
            ProviderTopScorer(
                player=_player_from_dict(index[row["player_id"]][0], row["team_id"]),
                team=_team(row["team_id"]),
                season=season,
                goals=row["goals"],
                assists=row["assists"],
                appearances=row["appearances"],
                penalties=row["penalties"],
            )
            for row in mock_extras.top_scorers(competition_id, salt=season)
            if row["player_id"] in index
        ]
