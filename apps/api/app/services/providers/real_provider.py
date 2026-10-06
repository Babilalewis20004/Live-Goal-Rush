"""Real football-data provider adapter (inactive by default).

This targets the shape of football-data.org's free-tier v4 API as a
concrete example of how a real provider slots in behind
`FootballDataProvider` without the rest of the app changing. It is not
activated in Phase 1 because no API credentials are available in this
environment.

To activate it:
  1. Get a free API key from https://www.football-data.org/client/register
  2. Set in `.env`:
       FOOTBALL_DATA_PROVIDER=real
       FOOTBALL_API_BASE_URL=https://api.football-data.org/v4
       FOOTBALL_API_KEY=<your key>
  3. Restart the API. `app/services/providers/__init__.get_provider()` will
     pick this class up automatically -- no other code changes needed.

The free tier's competition/match coverage and rate limits are narrower
than the mock dataset, so response mapping here is best-effort and may
need adjusting to match the exact fields your plan returns.

Phase 5 -- plan-gated features. Match events, lineups and match statistics
exist only on football-data.org's paid plans, so they are OFF unless named in
`FOOTBALL_API_FEATURES` (comma separated: `events,lineups,statistics`). Turn
them on only when your plan includes them: `capabilities` then reports them,
the sync layer starts calling them, and the UI stops saying "not available".
The mapping for those three follows the v4 match resource's documented
`goals` / `bookings` / `substitutions` / `homeTeam.lineup` / `.bench` /
`.formation` / `.statistics` fields. It is covered by tests against
payloads of that shape, but has NOT been exercised against a live paid
account -- verify with your own key before relying on it.

Phase 4 capability matrix for this provider (see `capabilities`): standings
(with season, groups and the provider's form string), top scorers, team
squads, player profiles and team venues are supported. Match events,
lineups, match statistics and player match statistics are NOT available on
the free tier, so they are declared unsupported and the app shows an honest
"not available from this data provider" state instead of empty sections.
Dates of birth are deliberately not stored (data minimization), and
shirt numbers/qualification zones are not supplied by the API, so they stay
empty rather than guessed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import date

import httpx

from app.services.providers.base import FootballDataProvider
from app.services.providers.schemas import (
    ProviderCapabilities,
    ProviderCompetition,
    ProviderLineup,
    ProviderLineupPlayer,
    ProviderMatch,
    ProviderMatchEvent,
    ProviderPlayer,
    ProviderTeamMatchStatistics,
    ProviderSearchResult,
    ProviderStandingRow,
    ProviderTeam,
    ProviderTopScorer,
)

_STATUS_MAP = {
    "SCHEDULED": "scheduled",
    "TIMED": "scheduled",
    "IN_PLAY": "live",
    "PAUSED": "halftime",
    "FINISHED": "finished",
    "POSTPONED": "postponed",
    "SUSPENDED": "postponed",
    "CANCELLED": "cancelled",
}


logger = logging.getLogger(__name__)

PLAN_FEATURES = frozenset({"events", "lineups", "statistics"})
_DETAIL_TTL_SECONDS = 10.0
_CARD_TYPES = {"YELLOW": "yellow_card", "RED": "red_card", "YELLOW_RED": "second_yellow"}
_GOAL_TYPES = {"REGULAR": "goal", "OWN": "own_goal", "PENALTY": "penalty"}


def parse_features(value: str | Iterable[str] | None) -> frozenset[str]:
    """`"events, lineups"` -> {"events", "lineups"}; unknown names are
    ignored (with a warning) so a typo can't silently enable nothing."""
    if value is None:
        return frozenset()
    names = [v.strip().lower() for v in (value.split(",") if isinstance(value, str) else value)]
    names = [n for n in names if n]
    unknown = [n for n in names if n not in PLAN_FEATURES]
    if unknown:
        logger.warning("Ignoring unknown FOOTBALL_API_FEATURES entries: %s", ", ".join(unknown))
    return frozenset(n for n in names if n in PLAN_FEATURES)


def _season_year(season: str) -> str:
    """"2024/25" -> "2024": football-data's `?season=` is the start year."""
    return season[:4]


def _as_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(value) -> float | None:
    """Possession may arrive as 54, "54" or "54%"."""
    try:
        return float(str(value).rstrip("%")) if value is not None else None
    except (TypeError, ValueError):
        return None


def _position(raw: str | None) -> str | None:
    """Normalize football-data's position vocabulary ("Defence", "Centre-Back",
    "Offence", "Left Winger"...) onto the four groups the app uses."""
    if not raw:
        return None
    value = raw.lower()
    if "keeper" in value:
        return "Goalkeeper"
    if "defen" in value or "back" in value:
        return "Defender"
    if "midfield" in value:
        return "Midfielder"
    if any(word in value for word in ("offen", "forward", "winger", "striker", "attack")):
        return "Forward"
    return raw


def _season_label(season: dict | None) -> str | None:
    """"2025/26" for a season spanning two calendar years, "2026" for one
    that fits in a single year; `None` if the payload has no start date."""
    if not season or not season.get("startDate"):
        return None
    start = int(season["startDate"][:4])
    end = int(season["endDate"][:4]) if season.get("endDate") else start
    return f"{start}/{str(end)[-2:]}" if end != start else str(start)


def _form(raw: str | None) -> str | None:
    """"W,D,L,W,W" -> "WDLWW"."""
    if not raw:
        return None
    return raw.replace(",", "").replace(" ", "") or None


class RealFootballDataProvider(FootballDataProvider):
    def __init__(self, base_url: str, api_key: str, features: str | Iterable[str] | None = None) -> None:
        if not base_url or not api_key:
            raise RuntimeError(
                "RealFootballDataProvider requires FOOTBALL_API_BASE_URL and "
                "FOOTBALL_API_KEY to be set. Falling back is not automatic -- "
                "set FOOTBALL_DATA_PROVIDER=mock to use the mock provider instead."
            )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Auth-Token": api_key},
            timeout=10.0,
        )
        self._features = parse_features(features)
        self._detail_cache: dict[str, tuple[float, dict]] = {}

    def _team(self, raw: dict) -> ProviderTeam:
        return ProviderTeam(
            provider_id=str(raw["id"]),
            name=raw["name"],
            short_name=raw.get("shortName") or raw.get("tla"),
            country=raw.get("area", {}).get("name"),
            logo_url=raw.get("crest"),
            venue=raw.get("venue"),
        )

    def _player(self, raw: dict, team: ProviderTeam | None = None) -> ProviderPlayer:
        return ProviderPlayer(
            provider_id=str(raw["id"]),
            name=raw["name"],
            position=_position(raw.get("position") or raw.get("section")),
            nationality=raw.get("nationality"),
            team=team,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            match_events="events" in self._features,
            lineups="lineups" in self._features,
            match_statistics="statistics" in self._features,
            player_statistics=False,  # no per-player match statistics in the v4 API
            team_squads=True,
            player_profiles=True,
            standings=True,
            top_scorers=True,
            venues=True,
            historical_seasons=True,
        )

    def _competition(self, raw: dict) -> ProviderCompetition:
        return ProviderCompetition(
            provider_id=str(raw["id"]),
            name=raw["name"],
            country=raw.get("area", {}).get("name"),
            logo_url=raw.get("emblem"),
            type="cup" if raw.get("type") == "CUP" else "league",
        )

    def _match(self, raw: dict) -> ProviderMatch:
        score = raw.get("score", {})
        full_time = score.get("fullTime", {})
        half_time = score.get("halfTime", {})
        return ProviderMatch(
            provider_id=str(raw["id"]),
            competition=self._competition(raw["competition"]),
            home_team=self._team(raw["homeTeam"]),
            away_team=self._team(raw["awayTeam"]),
            kickoff_time=raw["utcDate"],
            status=_STATUS_MAP.get(raw.get("status", ""), "scheduled"),
            home_score=full_time.get("home") or 0,
            away_score=full_time.get("away") or 0,
            half_time_home_score=half_time.get("home"),
            half_time_away_score=half_time.get("away"),
            venue=raw.get("venue"),
            minute=raw.get("minute"),
            # the free tier has no event timeline; the paid `events` feature
            # maps goals/bookings/substitutions when the payload has them
            events=self._events(raw) if "events" in self._features else [],
        )

    def _events(self, raw: dict) -> list[ProviderMatchEvent]:
        teams = {str(raw[k]["id"]): self._team(raw[k]) for k in ("homeTeam", "awayTeam") if raw.get(k)}

        def team_of(ref: dict | None) -> ProviderTeam | None:
            # Event payloads reference teams by id/name only; resolve to the
            # match's full team so a thin payload can't blank a stored team.
            return teams.get(str(ref["id"])) if ref and ref.get("id") is not None else None

        def person(ref: dict | None, team: ProviderTeam | None) -> ProviderPlayer | None:
            return self._player(ref, team) if ref and ref.get("id") is not None else None

        mid = raw["id"]
        events: list[ProviderMatchEvent] = []
        for goal in raw.get("goals") or []:
            team = team_of(goal.get("team"))
            scorer = person(goal.get("scorer"), team)
            events.append(
                ProviderMatchEvent(
                    provider_id=f"fd{mid}-goal-{goal.get('minute')}-{goal.get('injuryTime') or 0}-{scorer.provider_id if scorer else 'x'}",
                    event_type=_GOAL_TYPES.get(goal.get("type", "REGULAR"), "goal"),
                    minute=goal.get("minute") or 0,
                    extra_minute=goal.get("injuryTime"),
                    team=team,
                    player=scorer,
                    assist_player=person(goal.get("assist"), team),
                )
            )
        for booking in raw.get("bookings") or []:
            team = team_of(booking.get("team"))
            player = person(booking.get("player"), team)
            events.append(
                ProviderMatchEvent(
                    provider_id=f"fd{mid}-card-{booking.get('minute')}-{player.provider_id if player else 'x'}-{booking.get('card')}",
                    event_type=_CARD_TYPES.get(booking.get("card", "YELLOW"), "yellow_card"),
                    minute=booking.get("minute") or 0,
                    team=team,
                    player=player,
                )
            )
        for sub in raw.get("substitutions") or []:
            team = team_of(sub.get("team"))
            on, off = person(sub.get("playerIn"), team), person(sub.get("playerOut"), team)
            events.append(
                ProviderMatchEvent(
                    provider_id=f"fd{mid}-sub-{sub.get('minute')}-{on.provider_id if on else 'x'}",
                    event_type="substitution",
                    minute=sub.get("minute") or 0,
                    team=team,
                    player=on,  # coming on (see MatchEventOut convention)
                    assist_player=off,  # going off
                )
            )
        events.sort(key=lambda e: (e.minute, e.extra_minute or 0))
        return events

    async def _detail(self, match_id: str) -> dict | None:
        """The match resource (`/matches/{id}`) is where events, lineups and
        statistics live; one live poll needs it for up to three features, so it
        is cached for a few seconds instead of fetched three times."""
        cached = self._detail_cache.get(match_id)
        if cached and time.monotonic() - cached[0] < _DETAIL_TTL_SECONDS:
            return cached[1]
        resp = await self._client.get(f"/matches/{match_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        self._detail_cache[match_id] = (time.monotonic(), data)
        if len(self._detail_cache) > 64:
            oldest = min(self._detail_cache, key=lambda k: self._detail_cache[k][0])
            self._detail_cache.pop(oldest, None)
        return data

    async def get_live_matches(self) -> list[ProviderMatch]:
        resp = await self._client.get("/matches", params={"status": "LIVE"})
        resp.raise_for_status()
        raw_matches = resp.json().get("matches", [])
        if "events" in self._features:
            # List items carry no goals/bookings/substitutions: fetch each live
            # match's detail, or the sync would see "no events" and clear the
            # stored timeline.
            detailed = [await self._detail(str(m["id"])) for m in raw_matches]
            raw_matches = [d or m for d, m in zip(detailed, raw_matches, strict=True)]
        return [self._match(m) for m in raw_matches]

    async def get_fixtures(self, on_date: date) -> list[ProviderMatch]:
        iso = on_date.isoformat()
        resp = await self._client.get("/matches", params={"dateFrom": iso, "dateTo": iso})
        resp.raise_for_status()
        return [self._match(m) for m in resp.json().get("matches", [])]

    async def get_match(self, match_id: str) -> ProviderMatch | None:
        raw = await self._detail(match_id)
        return self._match(raw) if raw is not None else None

    async def get_competitions(self) -> list[ProviderCompetition]:
        resp = await self._client.get("/competitions")
        resp.raise_for_status()
        return [self._competition(c) for c in resp.json().get("competitions", [])]

    async def get_competition_fixtures(self, competition_id: str) -> list[ProviderMatch]:
        resp = await self._client.get(f"/competitions/{competition_id}/matches")
        resp.raise_for_status()
        return [self._match(m) for m in resp.json().get("matches", [])]

    async def get_standings(self, competition_id: str) -> list[ProviderStandingRow]:
        return await self._standings(competition_id, None)

    async def get_historical_standings(self, competition_id: str, season: str) -> list[ProviderStandingRow]:
        return await self._standings(competition_id, season)

    async def _standings(self, competition_id: str, season: str | None) -> list[ProviderStandingRow]:
        params = {"season": _season_year(season)} if season else None
        resp = await self._client.get(f"/competitions/{competition_id}/standings", params=params)
        if season and resp.status_code in (400, 403, 404):
            return []  # past seasons aren't available on every plan: "none", not a retry storm
        resp.raise_for_status()
        data = resp.json()
        season = _season_label(data.get("season"))
        rows: list[ProviderStandingRow] = []
        # A league has one TOTAL table; a group stage has one per group.
        for table in (t for t in data.get("standings", []) if t.get("type") == "TOTAL"):
            group = table.get("group")
            group_label = group.replace("_", " ").title() if group else None
            for row in table.get("table", []):
                rows.append(
                    ProviderStandingRow(
                        team=self._team(row["team"]),
                        season=season,
                        group=group_label,
                        form=_form(row.get("form")),
                        position=row["position"],
                        played=row["playedGames"],
                        won=row["won"],
                        drawn=row["draw"],
                        lost=row["lost"],
                        goals_for=row["goalsFor"],
                        goals_against=row["goalsAgainst"],
                        points=row["points"],
                    )
                )
        return rows

    async def get_top_scorers(self, competition_id: str) -> list[ProviderTopScorer]:
        return await self._scorers(competition_id, None)

    async def get_historical_top_scorers(self, competition_id: str, season: str) -> list[ProviderTopScorer]:
        return await self._scorers(competition_id, season)

    async def _scorers(self, competition_id: str, season: str | None) -> list[ProviderTopScorer]:
        params = {"season": _season_year(season)} if season else None
        resp = await self._client.get(f"/competitions/{competition_id}/scorers", params=params)
        if season and resp.status_code in (400, 403, 404):
            return []
        resp.raise_for_status()
        data = resp.json()
        season = _season_label(data.get("season"))
        scorers: list[ProviderTopScorer] = []
        for row in data.get("scorers", []):
            team = self._team(row["team"]) if row.get("team") else None
            scorers.append(
                ProviderTopScorer(
                    player=self._player(row["player"], team),
                    team=team,
                    season=season,
                    goals=row.get("goals") or 0,
                    assists=row.get("assists"),
                    appearances=row.get("playedMatches"),
                    penalties=row.get("penalties"),
                )
            )
        return scorers

    async def get_team_squad(self, team_id: str) -> list[ProviderPlayer]:
        resp = await self._client.get(f"/teams/{team_id}")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        team = self._team(data)
        return [self._player(p, team) for p in data.get("squad", [])]

    async def get_player(self, player_id: str) -> ProviderPlayer | None:
        resp = await self._client.get(f"/persons/{player_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        current_team = data.get("currentTeam")
        return self._player(data, self._team(current_team) if current_team else None)

    async def get_team(self, team_id: str) -> ProviderTeam | None:
        resp = await self._client.get(f"/teams/{team_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._team(resp.json())

    async def get_team_fixtures(self, team_id: str) -> list[ProviderMatch]:
        resp = await self._client.get(f"/teams/{team_id}/matches")
        resp.raise_for_status()
        return [self._match(m) for m in resp.json().get("matches", [])]

    async def search(self, query: str) -> ProviderSearchResult:
        # The free tier has no unified search endpoint; a production
        # integration would query /teams?name= and /competitions and filter
        # client-side, or upgrade to a plan that supports search directly.
        return ProviderSearchResult(teams=[], competitions=[], players=[])

    async def get_lineups(self, match_id: str) -> list[ProviderLineup]:
        if "lineups" not in self._features:
            return []
        raw = await self._detail(match_id)
        if raw is None:
            return []
        lineups: list[ProviderLineup] = []
        for side in ("homeTeam", "awayTeam"):
            team_raw = raw.get(side) or {}
            starters, bench = team_raw.get("lineup") or [], team_raw.get("bench") or []
            if not starters and not bench:
                continue  # not published (yet)
            team = self._team(team_raw)
            players = [
                ProviderLineupPlayer(
                    player=self._player(p, team),
                    is_starter=is_starter,
                    position=_position(p.get("position")),
                    shirt_number=p.get("shirtNumber"),
                )
                for is_starter, group in ((True, starters), (False, bench))
                for p in group
            ]
            lineups.append(ProviderLineup(team=team, formation=team_raw.get("formation"), players=players))
        return lineups

    async def get_match_statistics(self, match_id: str) -> list[ProviderTeamMatchStatistics]:
        if "statistics" not in self._features:
            return []
        raw = await self._detail(match_id)
        if raw is None:
            return []
        result: list[ProviderTeamMatchStatistics] = []
        for side in ("homeTeam", "awayTeam"):
            team_raw = raw.get(side) or {}
            stats = team_raw.get("statistics")
            if not stats:
                continue
            result.append(
                ProviderTeamMatchStatistics(
                    team=self._team(team_raw),
                    possession=_as_float(stats.get("ball_possession")),
                    shots=_as_int(stats.get("shots")),
                    shots_on_target=_as_int(stats.get("shots_on_goal")),
                    corners=_as_int(stats.get("corner_kicks")),
                    fouls=_as_int(stats.get("fouls")),
                    offsides=_as_int(stats.get("offsides")),
                    yellow_cards=_as_int(stats.get("yellow_cards")),
                    red_cards=_as_int(stats.get("red_cards")),
                    # pass accuracy / xG are not part of this resource: stay unsupplied
                )
            )
        return result

    async def aclose(self) -> None:
        await self._client.aclose()
