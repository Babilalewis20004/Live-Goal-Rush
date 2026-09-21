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
"""

from __future__ import annotations

from datetime import date

import httpx

from app.services.providers.base import FootballDataProvider
from app.services.providers.schemas import (
    ProviderCompetition,
    ProviderMatch,
    ProviderSearchResult,
    ProviderStandingRow,
    ProviderTeam,
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
        table = next(
            (t["table"] for t in data.get("standings", []) if t.get("type") == "TOTAL"),
            [],
        )
        return [
            ProviderStandingRow(
                team=self._team(row["team"]),
                position=row["position"],
                played=row["playedGames"],
                won=row["won"],
                drawn=row["draw"],
                lost=row["lost"],
                goals_for=row["goalsFor"],
                goals_against=row["goalsAgainst"],
                points=row["points"],
            )
            for row in table
        ]

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
