"""API-Football (api-sports.io, v3) provider adapter.

Activate with, in `.env`:
    FOOTBALL_DATA_PROVIDER=api-football
    FOOTBALL_API_KEY=<your api-sports key>
    # optional: FOOTBALL_API_BASE_URL (default https://v3.football.api-sports.io)
    # optional: FOOTBALL_API_LEAGUE_IDS (comma separated API-Football league ids)

Scope. The account covers every league in the world (~1000 competitions,
800+ fixtures a day), which the app neither needs nor can afford quota-wise,
so the provider only exposes the leagues in `FOOTBALL_API_LEAGUE_IDS`:
competitions, date fixtures and live matches are filtered to that set.

Events. `/fixtures` list queries (by date / league / team) carry no events,
and the sync layer deletes stored events that are missing from a payload. So
every started match in a list result is enriched through `/fixtures?ids=`
(20 per request), which does carry events. `live=all` carries them already.

Seasons. API-Football addresses a season by its start year (2025 = 2025/26)
and requires it next to `league`. The current one and the label for each past
one come from `/leagues?id=` (cached for the life of the process).
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from app.services.providers.base import FootballDataProvider, ProviderQuotaExhausted
from app.services.providers.schemas import (
    ProviderCapabilities,
    ProviderCompetition,
    ProviderInjury,
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

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://v3.football.api-sports.io"
# Development scope: Premier League, La Liga, Serie A.
DEFAULT_LEAGUE_IDS = "39,140,135"

_STATUS_MAP = {
    "TBD": "scheduled",
    "NS": "scheduled",
    "1H": "live",
    "2H": "live",
    "ET": "live",
    "BT": "live",
    "P": "live",
    "LIVE": "live",
    "INT": "live",
    "HT": "halftime",
    "FT": "finished",
    "AET": "finished",
    "PEN": "finished",
    "PST": "postponed",
    "SUSP": "postponed",
    "CANC": "cancelled",
    "ABD": "cancelled",
    "AWD": "finished",
    "WO": "finished",
}
_IDS_PER_REQUEST = 20  # API-Football's cap for `/fixtures?ids=`
_POSITIONS = {"G": "Goalkeeper", "D": "Defender", "M": "Midfielder", "F": "Forward"}
_DETAIL_TTL_SECONDS = 10.0

# Response-cache lifetimes (seconds). The account has a daily request quota
# (7,500 on Pro), and the worker re-asks for the same slow-moving data every
# few minutes, so each endpoint is cached for about as long as it stays true.
_TTL_LEAGUE = 86_400  # competition metadata and season list
_TTL_STANDINGS = 600
_TTL_SCORERS = 1_800
_TTL_SEASON_FIXTURES = 1_800
_TTL_TODAY = 60
_TTL_NEAR_DATE = 900  # yesterday / the next week
_TTL_PAST_DATE = 21_600
_TTL_LIVE_DETAIL = 30  # `ids=` chunks that contain an in-play match
_TTL_FINISHED_DETAIL = 1_800
_TTL_LINEUPS = 600
_TTL_MATCH_STATS = 60
_TTL_PLAYER_STATS = 120
_TTL_TEAM = 86_400
_TTL_SQUAD = 21_600
_TTL_SEARCH = 600
_TTL_INJURIES = 1_800
_INJURY_FRESH_DAYS = 3
_CACHE_MAX_ENTRIES = 2_000
# When the day's remaining requests drop below this, only "essential" calls
# (live scores, single-match detail) are still made, so background syncs can
# never starve the live feed.
QUOTA_RESERVE = 750


def parse_league_ids(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip().isdigit()]


def _int(value) -> int | None:
    try:
        return int(str(value).rstrip("%")) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    try:
        return float(str(value).rstrip("%")) if value is not None else None
    except (TypeError, ValueError):
        return None


def _position(raw: str | None) -> str | None:
    """Normalize onto Goalkeeper/Defender/Midfielder/Forward."""
    if not raw:
        return None
    if raw in _POSITIONS:
        return _POSITIONS[raw]
    return "Forward" if raw == "Attacker" else raw


def _form(raw: str | None) -> str | None:
    return raw.replace(",", "").replace(" ", "") or None if raw else None


def _season_label(start: str | None, end: str | None, year: int) -> str:
    """"2025/26" for a season spanning two calendar years, "2026" otherwise."""
    s = int(start[:4]) if start else year
    e = int(end[:4]) if end else s
    return f"{s}/{str(e)[-2:]}" if e != s else str(s)


class ApiFootballProvider(FootballDataProvider):
    def __init__(self, api_key: str, base_url: str = "", league_ids: str | None = None) -> None:
        if not api_key:
            raise RuntimeError(
                "ApiFootballProvider requires FOOTBALL_API_KEY."
            )
        self._client = httpx.AsyncClient(
            base_url=base_url or DEFAULT_BASE_URL,
            headers={"x-apisports-key": api_key},
            timeout=15.0,
        )
        self._league_ids = parse_league_ids(league_ids if league_ids is not None else DEFAULT_LEAGUE_IDS)
        self._league_set = set(self._league_ids)
        # league id -> {"current": year, "labels": {year: label}}
        self._seasons: dict[str, dict] = {}
        self._detail_cache: dict[str, tuple[float, dict]] = {}
        self._response_cache: dict[tuple, tuple[float, list[dict]]] = {}
        self.requests_remaining: int | None = None
        self.requests_limit: int | None = None

    # -- transport --------------------------------------------------------

    async def _get(self, path: str, *, ttl: float = 0, essential: bool = False, **params) -> list[dict]:
        """GET `path`. `ttl` > 0 serves repeats from an in-process cache;
        non-`essential` calls are refused once the daily quota is nearly spent."""
        params = {k: v for k, v in params.items() if v is not None}
        key = (path, tuple(sorted(params.items())))
        now = time.monotonic()
        if ttl:
            hit = self._response_cache.get(key)
            if hit and hit[0] > now:
                return hit[1]
        if not essential and self.requests_remaining is not None and self.requests_remaining < QUOTA_RESERVE:
            raise ProviderQuotaExhausted(
                f"API-Football daily quota nearly spent ({self.requests_remaining} left, "
                f"reserve {QUOTA_RESERVE}); skipping {path}"
            )
        resp = await self._client.get(path, params=params)
        self._note_quota(resp)
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("errors")
        if errors:  # API-Football reports quota / plan / param errors with HTTP 200
            raise RuntimeError(f"API-Football {path}: {errors}")
        rows = data.get("response") or []
        if ttl:
            if len(self._response_cache) >= _CACHE_MAX_ENTRIES:
                self._response_cache = {k: v for k, v in self._response_cache.items() if v[0] > now}
                while len(self._response_cache) >= _CACHE_MAX_ENTRIES:
                    self._response_cache.pop(min(self._response_cache, key=lambda k: self._response_cache[k][0]))
            self._response_cache[key] = (now + ttl, rows)
        return rows

    def _note_quota(self, resp: httpx.Response) -> None:
        remaining = _int(resp.headers.get("x-ratelimit-requests-remaining"))
        if remaining is None:
            return
        self.requests_remaining = remaining
        self.requests_limit = _int(resp.headers.get("x-ratelimit-requests-limit")) or self.requests_limit
        if remaining in (QUOTA_RESERVE, 2 * QUOTA_RESERVE, 100):
            logger.warning("API-Football daily quota low: %d of %s requests left", remaining, self.requests_limit)

    async def _season_info(self, league_id: str) -> dict:
        info = self._seasons.get(league_id)
        if info is None:
            rows = await self._get("/leagues", ttl=_TTL_LEAGUE, id=league_id)
            seasons = rows[0]["seasons"] if rows else []
            current = next((s["year"] for s in seasons if s.get("current")), None)
            if current is None and seasons:
                current = max(s["year"] for s in seasons)
            info = {
                "current": current,
                "labels": {s["year"]: _season_label(s.get("start"), s.get("end"), s["year"]) for s in seasons},
            }
            self._seasons[league_id] = info
        return info

    async def _season_year(self, league_id: str, label: str | None) -> int | None:
        """"2024/25" -> 2024; `None` label -> the league's current season."""
        info = await self._season_info(league_id)
        if label is None:
            return info["current"]
        return int(label[:4])

    async def _season_text(self, league_id: str, year: int | None) -> str | None:
        if year is None:
            return None
        return (await self._season_info(league_id))["labels"].get(year)

    # -- mapping ----------------------------------------------------------

    @staticmethod
    def _team(raw: dict, venue: str | None = None, country: str | None = None) -> ProviderTeam:
        return ProviderTeam(
            provider_id=str(raw["id"]),
            name=raw["name"],
            short_name=raw.get("code"),
            country=country or raw.get("country"),
            logo_url=raw.get("logo"),
            venue=venue,
        )

    @staticmethod
    def _player(raw: dict, team: ProviderTeam | None = None, position: str | None = None) -> ProviderPlayer:
        return ProviderPlayer(
            provider_id=str(raw["id"]),
            name=raw["name"],
            position=_position(position or raw.get("position")),
            photo_url=raw.get("photo"),
            nationality=raw.get("nationality"),
            shirt_number=_int(raw.get("number")),
            team=team,
        )

    @staticmethod
    def _competition(raw: dict, country: str | None = None) -> ProviderCompetition:
        return ProviderCompetition(
            provider_id=str(raw["id"]),
            name=raw["name"],
            country=country or raw.get("country"),
            logo_url=raw.get("logo"),
            type="cup" if str(raw.get("type", "")).lower() == "cup" else "league",
        )

    def _events(self, raw: dict) -> list[ProviderMatchEvent]:
        fid = raw["fixture"]["id"]
        events: list[ProviderMatchEvent] = []
        for ev in raw.get("events") or []:
            kind, detail = ev.get("type"), ev.get("detail") or ""
            if kind == "Goal":
                if detail == "Missed Penalty":
                    continue
                event_type = {"Own Goal": "own_goal", "Penalty": "penalty"}.get(detail, "goal")
            elif kind == "Card":
                event_type = (
                    "red_card" if detail == "Red Card"
                    else "second_yellow" if detail.lower().startswith("second yellow")
                    else "yellow_card"
                )
            elif kind == "subst":
                event_type = "substitution"
            else:
                continue  # VAR decisions etc. have no counterpart in the app
            t = ev.get("time") or {}
            team = self._team(ev["team"]) if ev.get("team") else None
            actor = ev.get("player") if (ev.get("player") or {}).get("id") is not None else None
            other = ev.get("assist") if (ev.get("assist") or {}).get("id") is not None else None
            # Convention (see MatchEventOut): for a substitution `player` is
            # the one coming ON. API-Football puts the one going off in
            # `player` and the one coming on in `assist`.
            if event_type == "substitution":
                actor, other = other, actor
            player = self._player(actor, team) if actor else None
            events.append(
                ProviderMatchEvent(
                    provider_id=(
                        f"af{fid}-{event_type}-{t.get('elapsed')}-{t.get('extra') or 0}-"
                        f"{actor['id'] if actor else 'x'}-{other['id'] if other else 'x'}"
                    ),
                    event_type=event_type,
                    minute=t.get("elapsed") or 0,
                    extra_minute=t.get("extra"),
                    team=team,
                    player=player,
                    assist_player=self._player(other, team) if other else None,
                    event_detail=detail or None,
                    description=ev.get("comments"),
                )
            )
        events.sort(key=lambda e: (e.minute, e.extra_minute or 0))
        return events

    def _match(self, raw: dict) -> ProviderMatch:
        fx, goals = raw["fixture"], raw.get("goals") or {}
        half = (raw.get("score") or {}).get("halftime") or {}
        status = fx.get("status") or {}
        state = _STATUS_MAP.get(status.get("short", ""), "scheduled")
        return ProviderMatch(
            provider_id=str(fx["id"]),
            competition=self._competition(raw["league"]),
            home_team=self._team(raw["teams"]["home"]),
            away_team=self._team(raw["teams"]["away"]),
            kickoff_time=fx["date"],
            status=state,
            home_score=goals.get("home") or 0,
            away_score=goals.get("away") or 0,
            half_time_home_score=half.get("home"),
            half_time_away_score=half.get("away"),
            venue=(fx.get("venue") or {}).get("name"),
            minute=status.get("elapsed") if state == "live" else None,
            events=self._events(raw),
        )

    async def _enrich(self, rows: list[dict]) -> list[ProviderMatch]:
        """Attach events to started matches that came from a list query."""
        started = [
            r for r in rows
            if not r.get("events") and _STATUS_MAP.get(r["fixture"]["status"]["short"], "scheduled") != "scheduled"
        ]
        by_id: dict[int, dict] = {}
        for i in range(0, len(started), _IDS_PER_REQUEST):
            chunk = started[i : i + _IDS_PER_REQUEST]
            ids = "-".join(str(r["fixture"]["id"]) for r in chunk)
            live = any(_STATUS_MAP.get(r["fixture"]["status"]["short"]) in ("live", "halftime") for r in chunk)
            ttl = _TTL_LIVE_DETAIL if live else _TTL_FINISHED_DETAIL
            for detail in await self._get("/fixtures", ttl=ttl, ids=ids):
                by_id[detail["fixture"]["id"]] = detail
        return [self._match(by_id.get(r["fixture"]["id"], r)) for r in rows]

    def _tracked(self, rows: list[dict]) -> list[dict]:
        return [r for r in rows if str(r["league"]["id"]) in self._league_set]

    async def _detail(self, match_id: str) -> dict | None:
        cached = self._detail_cache.get(match_id)
        if cached and time.monotonic() - cached[0] < _DETAIL_TTL_SECONDS:
            return cached[1]
        rows = await self._get("/fixtures", essential=True, id=match_id)
        if not rows:
            return None
        self._detail_cache[match_id] = (time.monotonic(), rows[0])
        if len(self._detail_cache) > 64:
            self._detail_cache.pop(min(self._detail_cache, key=lambda k: self._detail_cache[k][0]), None)
        return rows[0]

    # -- capabilities -----------------------------------------------------

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

    # -- matches ----------------------------------------------------------

    async def get_live_matches(self) -> list[ProviderMatch]:
        rows = self._tracked(await self._get("/fixtures", essential=True, live="all"))
        return [self._match(r) for r in rows]

    async def get_fixtures(self, on_date: date) -> list[ProviderMatch]:
        delta = (on_date - date.today()).days
        ttl = _TTL_TODAY if delta == 0 else _TTL_NEAR_DATE if -1 <= delta <= 7 else _TTL_PAST_DATE
        rows = self._tracked(await self._get("/fixtures", ttl=ttl, date=on_date.isoformat()))
        return await self._enrich(rows)

    async def get_match(self, match_id: str) -> ProviderMatch | None:
        raw = await self._detail(match_id)
        return self._match(raw) if raw else None

    async def get_competition_fixtures(self, competition_id: str) -> list[ProviderMatch]:
        year = await self._season_year(competition_id, None)
        rows = await self._get("/fixtures", ttl=_TTL_SEASON_FIXTURES, league=competition_id, season=year)
        return await self._enrich(rows)

    async def get_team_fixtures(self, team_id: str) -> list[ProviderMatch]:
        # Last and next few: a team's full season spans every competition
        # it plays in, which would cost one request per 20 started matches.
        recent = await self._get("/fixtures", ttl=_TTL_NEAR_DATE, team=team_id, last=10)
        upcoming = await self._get("/fixtures", ttl=_TTL_NEAR_DATE, team=team_id, next=10)
        return await self._enrich(self._tracked(recent + upcoming))

    # -- competitions / tables -------------------------------------------

    async def get_competitions(self) -> list[ProviderCompetition]:
        competitions: list[ProviderCompetition] = []
        for league_id in self._league_ids:
            rows = await self._get("/leagues", ttl=_TTL_LEAGUE, id=league_id)
            if rows:
                competitions.append(self._competition(rows[0]["league"], (rows[0].get("country") or {}).get("name")))
        return competitions

    async def get_standings(self, competition_id: str) -> list[ProviderStandingRow]:
        return await self._standings(competition_id, None)

    async def get_historical_standings(self, competition_id: str, season: str) -> list[ProviderStandingRow]:
        return await self._standings(competition_id, season)

    async def _standings(self, competition_id: str, label: str | None) -> list[ProviderStandingRow]:
        year = await self._season_year(competition_id, label)
        if year is None:
            return []
        rows = await self._get("/standings", ttl=_TTL_STANDINGS, league=competition_id, season=year)
        if not rows:
            return []
        season = await self._season_text(competition_id, year)
        result: list[ProviderStandingRow] = []
        multi_group = len(rows[0]["league"].get("standings") or []) > 1
        for table in rows[0]["league"].get("standings") or []:
            for row in table:
                all_ = row["all"]
                result.append(
                    ProviderStandingRow(
                        team=self._team(row["team"]),
                        season=season,
                        group=(row.get("group") if multi_group else None),
                        description=row.get("description"),
                        form=_form(row.get("form")),
                        position=row["rank"],
                        played=all_["played"],
                        won=all_["win"],
                        drawn=all_["draw"],
                        lost=all_["lose"],
                        goals_for=all_["goals"]["for"] or 0,
                        goals_against=all_["goals"]["against"] or 0,
                        points=row["points"],
                    )
                )
        return result

    async def get_top_scorers(self, competition_id: str) -> list[ProviderTopScorer]:
        return await self._scorers(competition_id, None)

    async def get_historical_top_scorers(self, competition_id: str, season: str) -> list[ProviderTopScorer]:
        return await self._scorers(competition_id, season)

    async def _scorers(self, competition_id: str, label: str | None) -> list[ProviderTopScorer]:
        year = await self._season_year(competition_id, label)
        if year is None:
            return []
        season = await self._season_text(competition_id, year)
        scorers: list[ProviderTopScorer] = []
        for row in await self._get("/players/topscorers", ttl=_TTL_SCORERS, league=competition_id, season=year):
            stat = (row.get("statistics") or [{}])[0]
            team = self._team(stat["team"]) if stat.get("team") else None
            goals = stat.get("goals") or {}
            scorers.append(
                ProviderTopScorer(
                    player=self._player(row["player"], team),
                    team=team,
                    season=season,
                    goals=goals.get("total") or 0,
                    assists=goals.get("assists"),
                    appearances=(stat.get("games") or {}).get("appearences"),
                    penalties=(stat.get("penalty") or {}).get("scored"),
                )
            )
        return scorers

    # -- teams / players --------------------------------------------------

    async def get_team(self, team_id: str) -> ProviderTeam | None:
        rows = await self._get("/teams", ttl=_TTL_TEAM, id=team_id)
        if not rows:
            return None
        return self._team(rows[0]["team"], venue=(rows[0].get("venue") or {}).get("name"))

    async def get_team_squad(self, team_id: str) -> list[ProviderPlayer]:
        rows = await self._get("/players/squads", ttl=_TTL_SQUAD, team=team_id)
        if not rows:
            return []
        team = self._team(rows[0]["team"])
        return [self._player(p, team) for p in rows[0].get("players") or []]

    def _club_stat(self, stats: list[dict]) -> dict:
        """A player has one statistics entry per team and competition, and
        national-team entries can come first. Prefer an entry from a tracked
        league (always a club); otherwise the one with the most appearances,
        which is the club in practice."""
        if not stats:
            return {}
        tracked = [s for s in stats if str((s.get("league") or {}).get("id")) in self._league_set]
        pool = tracked or stats
        return max(pool, key=lambda s: (s.get("games") or {}).get("appearences") or 0)

    async def get_player(self, player_id: str) -> ProviderPlayer | None:
        # `/players` needs a season; try the current European one, then the previous.
        today = date.today()
        start = today.year if today.month >= 7 else today.year - 1
        for year in (start, start - 1):
            rows = await self._get("/players", ttl=_TTL_SQUAD, id=player_id, season=year)
            if rows:
                stat = self._club_stat(rows[0].get("statistics") or [])
                team = self._team(stat["team"]) if stat.get("team") else None
                return self._player(rows[0]["player"], team, (stat.get("games") or {}).get("position"))
        return None

    async def get_team_injuries(self, team_id: str) -> list[ProviderInjury]:
        today = date.today()
        season = today.year if today.month >= 7 else today.year - 1
        by_player: dict[str, ProviderInjury] = {}
        for row in await self._get("/injuries", ttl=_TTL_INJURIES, team=team_id, season=season):
            player = row.get("player") or {}
            if player.get("id") is None:
                continue
            team = self._team(row["team"]) if row.get("team") else None
            when = (row.get("fixture") or {}).get("date")
            injury = ProviderInjury(
                player=self._player(player, team),
                team=team,
                kind="doubtful" if str(player.get("type", "")).lower() == "questionable" else "missing",
                reason=player.get("reason"),
                match_date=when,
            )
            known = by_player.get(injury.player.provider_id)
            # one row per player: the most recent fixture wins
            if known is None or (when and known.match_date and injury.match_date > known.match_date):
                by_player[injury.player.provider_id] = injury
        # The feed is a history of absences per fixture. Only absences tied to a
        # recent or upcoming fixture are current; older rows would show someone
        # who has since returned.
        horizon = datetime.now(timezone.utc) - timedelta(days=_INJURY_FRESH_DAYS)
        current = [i for i in by_player.values() if i.match_date and i.match_date >= horizon]
        return sorted(current, key=lambda i: i.match_date, reverse=True)

    async def search(self, query: str) -> ProviderSearchResult:
        if len(query.strip()) < 3:  # API-Football rejects shorter search terms
            return ProviderSearchResult()
        teams = await self._get("/teams", ttl=_TTL_SEARCH, search=query.strip())
        leagues = await self._get("/leagues", ttl=_TTL_SEARCH, search=query.strip())
        return ProviderSearchResult(
            teams=[self._team(t["team"], venue=(t.get("venue") or {}).get("name")) for t in teams[:20]],
            competitions=[
                self._competition(lg["league"], (lg.get("country") or {}).get("name"))
                for lg in leagues
                if str(lg["league"]["id"]) in self._league_set
            ],
            players=[],  # `/players?search=` also requires a league id
        )

    # -- match detail -----------------------------------------------------

    async def get_lineups(self, match_id: str) -> list[ProviderLineup]:
        lineups: list[ProviderLineup] = []
        for entry in await self._get("/fixtures/lineups", ttl=_TTL_LINEUPS, fixture=match_id):
            team = self._team(entry["team"])
            players = [
                ProviderLineupPlayer(
                    player=self._player(p["player"], team, p["player"].get("pos")),
                    is_starter=is_starter,
                    position=_position(p["player"].get("pos")),
                    shirt_number=_int(p["player"].get("number")),
                )
                for is_starter, group in ((True, entry.get("startXI")), (False, entry.get("substitutes")))
                for p in group or []
            ]
            lineups.append(ProviderLineup(team=team, formation=entry.get("formation"), players=players))
        return lineups

    async def get_match_statistics(self, match_id: str) -> list[ProviderTeamMatchStatistics]:
        result: list[ProviderTeamMatchStatistics] = []
        for entry in await self._get("/fixtures/statistics", ttl=_TTL_MATCH_STATS, fixture=match_id):
            stats = {s["type"]: s["value"] for s in entry.get("statistics") or []}
            result.append(
                ProviderTeamMatchStatistics(
                    team=self._team(entry["team"]),
                    possession=_float(stats.get("Ball Possession")),
                    shots=_int(stats.get("Total Shots")),
                    shots_on_target=_int(stats.get("Shots on Goal")),
                    corners=_int(stats.get("Corner Kicks")),
                    fouls=_int(stats.get("Fouls")),
                    offsides=_int(stats.get("Offsides")),
                    yellow_cards=_int(stats.get("Yellow Cards")),
                    red_cards=_int(stats.get("Red Cards")),
                    pass_accuracy=_float(stats.get("Passes %")),
                    expected_goals=_float(stats.get("expected_goals")),
                )
            )
        return result

    async def get_player_statistics(self, match_id: str) -> list[ProviderPlayerMatchStatistics]:
        result: list[ProviderPlayerMatchStatistics] = []
        for entry in await self._get("/fixtures/players", ttl=_TTL_PLAYER_STATS, fixture=match_id):
            team = self._team(entry["team"])
            for p in entry.get("players") or []:
                s = (p.get("statistics") or [{}])[0]
                games, shots = s.get("games") or {}, s.get("shots") or {}
                goals, passes = s.get("goals") or {}, s.get("passes") or {}
                tackles, cards = s.get("tackles") or {}, s.get("cards") or {}
                result.append(
                    ProviderPlayerMatchStatistics(
                        player=self._player(p["player"], team, games.get("position")),
                        team=team,
                        minutes_played=games.get("minutes"),
                        goals=goals.get("total"),
                        assists=goals.get("assists"),
                        shots=shots.get("total"),
                        shots_on_target=shots.get("on"),
                        passes=passes.get("total"),
                        key_passes=passes.get("key"),
                        tackles=tackles.get("total"),
                        interceptions=tackles.get("interceptions"),
                        blocks=tackles.get("blocks"),
                        yellow_cards=cards.get("yellow"),
                        red_cards=cards.get("red"),
                        fouls_committed=(s.get("fouls") or {}).get("committed"),
                        # pass_accuracy / clearances are not supplied as rates/counts: left unset
                    )
                )
        return result

    async def aclose(self) -> None:
        await self._client.aclose()
