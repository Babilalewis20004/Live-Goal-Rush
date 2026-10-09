"""Deterministic football fixtures for Phase 6b tests: teams, a competition, and
matches with exactly the scores/statistics a test states. Nothing random, nothing
copied from real fixtures."""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

from app.models.competition import Competition
from app.models.enums import MatchStatus
from app.models.match import Match
from app.models.player import Player
from app.models.statistics import MatchStatistic, PlayerMatchStatistic
from app.models.team import Team

_ids = itertools.count(1)
NOW = datetime.now(timezone.utc).replace(microsecond=0)
"""Fixtures are placed relative to "now" so upcoming/finished status stays consistent with the real clock."""


async def make_competition(sf, name="Test League") -> int:
    async with sf() as s:
        c = Competition(provider_id=f"c{next(_ids)}", name=name)
        s.add(c)
        await s.commit()
        return c.id


async def make_team(sf, name) -> int:
    async with sf() as s:
        t = Team(provider_id=f"t{next(_ids)}", name=name)
        s.add(t)
        await s.commit()
        return t.id


async def make_player(sf, name, team_id) -> int:
    async with sf() as s:
        p = Player(provider_id=f"p{next(_ids)}", name=name, team_id=team_id)
        s.add(p)
        await s.commit()
        return p.id


async def make_match(sf, comp, home, away, days_ago, hs=0, as_=0, status=MatchStatus.FINISHED, stats=None, now=NOW) -> int:
    """`days_ago` may be negative for a future fixture. `stats` = {team_id: {column: value}}."""
    async with sf() as s:
        m = Match(
            provider_id=f"m{next(_ids)}", competition_id=comp, home_team_id=home, away_team_id=away,
            kickoff_time=now - timedelta(days=days_ago), status=status, home_score=hs, away_score=as_,
        )
        s.add(m)
        await s.flush()
        for team_id, columns in (stats or {}).items():
            s.add(MatchStatistic(match_id=m.id, team_id=team_id, **columns))
        await s.commit()
        return m.id


async def add_player_stats(sf, match_id, player_id, team_id, **columns) -> None:
    async with sf() as s:
        s.add(PlayerMatchStatistic(match_id=match_id, player_id=player_id, team_id=team_id, **columns))
        await s.commit()


async def history(sf, comp, home, away, results, start_days_ago=60, step=7):
    """Finished matches, oldest first: `results` = [(home_id_is_home, hs, as)] where the flag says whether
    `home` hosted. Returns ids."""
    ids = []
    for i, (home_hosted, hs, as_) in enumerate(results):
        h, a = (home, away) if home_hosted else (away, home)
        ids.append(await make_match(sf, comp, h, a, start_days_ago - i * step, hs, as_))
    return ids
