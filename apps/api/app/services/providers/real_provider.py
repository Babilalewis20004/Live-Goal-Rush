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

from datetime import date

import httpx

from app.services.providers.base import FootballDataProvider
from app.services.providers.schemas import (
    ProviderCapabilities,
    ProviderCompetition,
    ProviderMatch,
    ProviderPlayer,
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
    def __init__(self, base_url: str, api_key: str) -> None:
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
            match_events=False,
            lineups=False,
            match_statistics=False,
            player_statistics=False,
            team_squads=True,
            player_profiles=True,
            standings=True,
            top_scorers=True,
            venues=True,
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
            events=[],  # the free tier does not expose an event timeline
        )

    async def get_live_matches(self) -> list[ProviderMatch]:
        resp = await self._client.get("/matches", params={"status": "LIVE"})
        resp.raise_for_status()
        return [self._match(m) for m in resp.json().get("matches", [])]

    async def get_fixtures(self, on_date: date) -> list[ProviderMatch]:
        iso = on_date.isoformat()
        resp = await self._client.get("/matches", params={"dateFrom": iso, "dateTo": iso})
        resp.raise_for_status()
        return [self._match(m) for m in resp.json().get("matches", [])]

    async def get_match(self, match_id: str) -> ProviderMatch | None:
        resp = await self._client.get(f"/matches/{match_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._match(resp.json())

    async def get_competitions(self) -> list[ProviderCompetition]:
        resp = await self._client.get("/competitions")
        resp.raise_for_status()
        return [self._competition(c) for c in resp.json().get("competitions", [])]

    async def get_competition_fixtures(self, competition_id: str) -> list[ProviderMatch]:
        resp = await self._client.get(f"/competitions/{competition_id}/matches")
        resp.raise_for_status()
        return [self._match(m) for m in resp.json().get("matches", [])]

    async def get_standings(self, competition_id: str) -> list[ProviderStandingRow]:
        resp = await self._client.get(f"/competitions/{competition_id}/standings")
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
        resp = await self._client.get(f"/competitions/{competition_id}/scorers")
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

    async def aclose(self) -> None:
        await self._client.aclose()
