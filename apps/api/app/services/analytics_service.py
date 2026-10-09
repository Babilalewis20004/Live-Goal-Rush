"""Team and player analytics and match comparison (Phase 6b).

Everything is aggregated from rows the platform already stores (finished
matches, per-match team statistics, per-match player statistics). Nothing is
estimated or filled in: a metric the provider never supplied has `value=None`
and `sample=0`, and the response lists what the platform cannot hold at all.

The full result is cached once per (entity, scope, window); the caller's plan
only decides which parts of that cached object are returned, so there is no
per-user cache to go stale when a subscription changes.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.competition import Competition
from app.models.enums import MatchStatus
from app.models.match import Match
from app.models.player import Player
from app.models.statistics import MatchStatistic, PlayerMatchStatistic, PlayerSeasonStatistic
from app.models.team import Team
from app.schemas.analytics import (
    ComparisonRow,
    MatchComparisonOut,
    PlayerAnalyticsOut,
    PlayerMatchLine,
    PlayerSeasonLine,
    RecordOut,
    Stat,
    TeamAnalyticsOut,
)
from app.schemas.team import TeamOut
from app.services.analytics_math import safe_div
from app.services.cache import CacheAside
from app.services.football_service import NotFoundError
from app.services.form_service import FormService
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

WINDOWS = (5, 10, 20, 38)
FREE_MAX_WINDOW = 10
DEFAULT_WINDOW = 10

# Metrics the data model has no column for; always reported as unavailable, never zero.
TEAM_UNAVAILABLE = ["progressive_passes", "expected_assists"]
PLAYER_UNAVAILABLE = ["expected_goals", "expected_assists", "progressive_actions"]

BASIC_ATTACK = ("goals", "goals_per_match")
BASIC_DEFENCE = ("goals_conceded", "goals_conceded_per_match", "clean_sheets")
TEAM_LOCKED_SECTIONS = ["attack", "possession", "defence", "discipline"]


def _stat(values: Iterable[float | int | None], mode: str = "sum") -> Stat:
    present = [v for v in values if v is not None]
    if not present:
        return Stat(value=None, sample=0)
    total = sum(present)
    return Stat(value=round(total if mode == "sum" else total / len(present), 2), sample=len(present))


def _per_match(total: Stat) -> Stat:
    return Stat(value=safe_div(total.value, total.sample), sample=total.sample)


class AnalyticsService:
    def __init__(self, db: AsyncSession, cache: CacheAside | None = None) -> None:
        self.db = db
        self.cache = cache
        self.form = FormService(db, cache)

    # -- team ---------------------------------------------------------------------------------

    async def _team(self, team_id: int) -> Team:
        team = await self.db.get(Team, team_id)
        if team is None:
            raise NotFoundError(f"Team {team_id} not found")
        return team

    async def _finished_matches(
        self, team_id: int, scope: str, window: int, before: datetime | None = None, exclude: int | None = None
    ) -> list[Match]:
        side = {
            "home": Match.home_team_id == team_id,
            "away": Match.away_team_id == team_id,
        }.get(scope, or_(Match.home_team_id == team_id, Match.away_team_id == team_id))
        conditions = [Match.status == MatchStatus.FINISHED, side]
        if before is not None:
            conditions.append(Match.kickoff_time < before)
        if exclude is not None:
            conditions.append(Match.id != exclude)
        stmt = select(Match).where(*conditions).order_by(Match.kickoff_time.desc()).limit(window)
        return list((await self.db.execute(stmt)).scalars())

    async def compute_team_analytics(
        self, team_id: int, scope: str = "overall", window: int = DEFAULT_WINDOW,
        before: datetime | None = None, exclude: int | None = None,
    ) -> TeamAnalyticsOut:
        """The full (Premium-shaped) analytics for a team. Cached by callers."""
        team = await self._team(team_id)
        matches = await self._finished_matches(team_id, scope, window, before, exclude)
        ids = [m.id for m in matches]
        n = len(matches)

        gf, ga = [], []
        for m in matches:
            home = m.home_team_id == team_id
            gf.append(m.home_score if home else m.away_score)
            ga.append(m.away_score if home else m.home_score)

        wins = sum(a > b for a, b in zip(gf, ga))
        draws = sum(a == b for a, b in zip(gf, ga))
        losses = n - wins - draws

        stats: dict[int, MatchStatistic] = {}
        players: dict[int, dict] = defaultdict(dict)
        if ids:
            stats = {
                s.match_id: s
                for s in (
                    await self.db.execute(
                        select(MatchStatistic).where(MatchStatistic.match_id.in_(ids), MatchStatistic.team_id == team_id)
                    )
                ).scalars()
            }
            cols = {
                name: func.sum(getattr(PlayerMatchStatistic, name))
                for name in ("assists", "key_passes", "passes", "tackles", "interceptions", "clearances", "blocks")
            }
            rows = await self.db.execute(
                select(PlayerMatchStatistic.match_id, *[c.label(k) for k, c in cols.items()])
                .where(PlayerMatchStatistic.match_id.in_(ids), PlayerMatchStatistic.team_id == team_id)
                .group_by(PlayerMatchStatistic.match_id)
            )
            for row in rows:
                players[row.match_id] = {k: getattr(row, k) for k in cols}

        def team_vals(field: str) -> list:
            return [getattr(stats[i], field) if i in stats else None for i in ids]

        def player_vals(field: str) -> list:
            return [players[i].get(field) if i in players else None for i in ids]

        goals = _stat(gf)
        shots = _stat(team_vals("shots"))
        # Conversion only over matches where shots are known, so a missing shot count never inflates it.
        both = [(g, s) for g, s in zip(gf, team_vals("shots")) if s is not None]
        conversion = Stat(
            value=safe_div(sum(g for g, _ in both), sum(s for _, s in both)) if both and sum(s for _, s in both) else None,
            sample=len(both),
        )
        if conversion.value is not None:
            conversion = Stat(value=round(conversion.value * 100, 1), sample=conversion.sample)
        xg = _stat(team_vals("expected_goals"))
        conceded = _stat(ga)

        attack = {
            "goals": goals,
            "goals_per_match": _per_match(goals),
            "shots": shots,
            "shots_per_match": _per_match(shots),
            "shots_on_target": _stat(team_vals("shots_on_target")),
            "shot_conversion_pct": conversion,
            "expected_goals": xg,
            "expected_goals_per_match": _per_match(xg),
            "assists": _stat(player_vals("assists")),
            "chances_created": _stat(player_vals("key_passes")),
        }
        possession = {
            "possession_pct": _stat(team_vals("possession"), "mean"),
            "pass_accuracy_pct": _stat(team_vals("pass_accuracy"), "mean"),
            "passes": _stat(player_vals("passes")),
        }
        defence = {
            "goals_conceded": conceded,
            "goals_conceded_per_match": _per_match(conceded),
            "clean_sheets": Stat(value=float(sum(g == 0 for g in ga)), sample=n) if n else Stat(),
            "tackles": _stat(player_vals("tackles")),
            "interceptions": _stat(player_vals("interceptions")),
            "clearances": _stat(player_vals("clearances")),
            "blocks": _stat(player_vals("blocks")),
        }
        discipline = {
            "yellow_cards": _stat(team_vals("yellow_cards")),
            "red_cards": _stat(team_vals("red_cards")),
            "fouls": _stat(team_vals("fouls")),
        }

        limitations: list[str] = []
        if n == 0:
            limitations.append("No finished matches are stored for this selection.")
        elif n < window:
            limitations.append(f"Only {n} of the last {window} matches are stored.")
        if n and not stats:
            limitations.append("The data provider supplied no match statistics for these matches; only results are shown.")
        elif n and len(stats) < n:
            limitations.append(f"Match statistics exist for {len(stats)} of {n} matches; per-metric samples are shown.")

        return TeamAnalyticsOut(
            team_id=team_id,
            team_name=team.name,
            scope=scope,  # type: ignore[arg-type]
            window=window,
            matches_considered=n,
            data_timestamp=matches[0].kickoff_time if matches else None,
            generated_at=datetime.now(timezone.utc),
            tier="full",
            record=RecordOut(
                played=n, wins=wins, draws=draws, losses=losses, points=wins * 3 + draws,
                points_per_match=safe_div(wins * 3 + draws, n),
            ),
            attack=attack,
            possession=possession,
            defence=defence,
            discipline=discipline,
            unavailable=list(TEAM_UNAVAILABLE),
            limitations=limitations,
        )

    async def team_analytics(self, team_id: int, scope: str = "overall", window: int = DEFAULT_WINDOW) -> TeamAnalyticsOut:
        """Cached full analytics (see `shape_team` for the plan-dependent view)."""
        if scope not in ("overall", "home", "away"):
            raise ValueError(f"Unknown scope {scope!r}")
        if window not in WINDOWS:
            raise ValueError(f"Window must be one of {WINDOWS}")

        async def load() -> TeamAnalyticsOut:
            try:
                out = await self.compute_team_analytics(team_id, scope, window)
            except NotFoundError:
                raise
            except Exception:
                metrics.count("analytics_generation_failures_total")
                raise
            metrics.count("analytics_generation_total")
            return out

        if self.cache is None:
            return await load()
        from app.core.redis_keys import RedisKeys

        return await self.cache.get_or_set_model(
            RedisKeys.team_analytics(team_id, scope, window), TeamAnalyticsOut, load,
            ttl_seconds=settings.analytics_cache_ttl_seconds,
        )

    @staticmethod
    def shape_team(full: TeamAnalyticsOut, premium: bool) -> TeamAnalyticsOut:
        if premium:
            return full
        return full.model_copy(
            update=dict(
                tier="basic",
                attack={k: v for k, v in full.attack.items() if k in BASIC_ATTACK},
                defence={k: v for k, v in full.defence.items() if k in BASIC_DEFENCE},
                possession={},
                discipline={},
                locked=list(TEAM_LOCKED_SECTIONS),
                unavailable=[],
            )
        )

    # -- player ---------------------------------------------------------------------------------

    async def compute_player_analytics(self, player_id: int, window: int = 10) -> PlayerAnalyticsOut:
        player = await self.db.get(Player, player_id)
        if player is None:
            raise NotFoundError(f"Player {player_id} not found")

        season_rows = (
            await self.db.execute(
                select(PlayerSeasonStatistic, Competition.name)
                .join(Competition, Competition.id == PlayerSeasonStatistic.competition_id)
                .where(PlayerSeasonStatistic.player_id == player_id)
                .order_by(PlayerSeasonStatistic.season.desc(), Competition.name)
            )
        ).all()
        seasons = [
            PlayerSeasonLine(
                competition_id=s.competition_id, competition_name=name, season=s.season,
                appearances=s.appearances, goals=s.goals, assists=s.assists,
            )
            for s, name in season_rows
        ]

        lines = (
            await self.db.execute(
                select(PlayerMatchStatistic, Match)
                .join(Match, Match.id == PlayerMatchStatistic.match_id)
                .where(PlayerMatchStatistic.player_id == player_id, Match.status == MatchStatus.FINISHED)
                .order_by(Match.kickoff_time.desc())
                .limit(window)
            )
        ).all()
        team_names: dict[int, str] = {}
        need = {m.home_team_id for _, m in lines} | {m.away_team_id for _, m in lines}
        if need:
            team_names = dict((await self.db.execute(select(Team.id, Team.name).where(Team.id.in_(need)))).all())

        recent = []
        for ps, m in lines:
            opp = m.away_team_id if ps.team_id == m.home_team_id else m.home_team_id
            recent.append(
                PlayerMatchLine(
                    match_id=m.id, kickoff_time=m.kickoff_time, opponent=team_names.get(opp, "Unknown"),
                    minutes=ps.minutes_played, goals=ps.goals, assists=ps.assists, shots=ps.shots,
                    shots_on_target=ps.shots_on_target, key_passes=ps.key_passes, tackles=ps.tackles,
                    yellow_cards=ps.yellow_cards, red_cards=ps.red_cards,
                )
            )

        fields = ("minutes_played", "goals", "assists", "shots", "shots_on_target", "passes", "key_passes",
                  "tackles", "interceptions", "clearances", "blocks", "yellow_cards", "red_cards")
        totals = {f: _stat(getattr(ps, f) for ps, _ in lines) for f in fields}
        minutes = totals["minutes_played"].value
        per_90 = {
            f: Stat(value=round(totals[f].value / minutes * 90, 2) if minutes and totals[f].value is not None else None,
                    sample=totals[f].sample)
            for f in ("goals", "assists", "shots", "shots_on_target", "key_passes", "tackles", "interceptions")
        }
        involvements = [(ps.goals or 0) + (ps.assists or 0) for ps, _ in reversed(lines)]

        limitations: list[str] = []
        if not lines:
            limitations.append("No per-match statistics are stored for this player.")
        elif len(lines) < window:
            limitations.append(f"Only {len(lines)} of the last {window} matches have statistics.")
        metrics.count("analytics_generation_total")
        return PlayerAnalyticsOut(
            player_id=player_id, player_name=player.name, generated_at=datetime.now(timezone.utc), tier="full",
            seasons=seasons, window=window, matches_with_statistics=len(lines), totals=totals, per_90=per_90,
            recent=recent, form_goal_involvements=involvements, unavailable=list(PLAYER_UNAVAILABLE),
            limitations=limitations,
        )

    async def player_analytics(self, player_id: int, window: int = 10) -> PlayerAnalyticsOut:
        if window not in WINDOWS:
            raise ValueError(f"Window must be one of {WINDOWS}")
        if self.cache is None:
            return await self.compute_player_analytics(player_id, window)
        from app.core.redis_keys import RedisKeys

        return await self.cache.get_or_set_model(
            RedisKeys.player_analytics(player_id, window), PlayerAnalyticsOut,
            lambda: self.compute_player_analytics(player_id, window),
            ttl_seconds=settings.analytics_cache_ttl_seconds,
        )

    @staticmethod
    def shape_player(full: PlayerAnalyticsOut, premium: bool) -> PlayerAnalyticsOut:
        if premium:
            return full
        return full.model_copy(
            update=dict(
                tier="basic", window=0, matches_with_statistics=0, totals={}, per_90={}, recent=[],
                form_goal_involvements=[], unavailable=[], limitations=[],
                locked=["recent_matches", "totals", "per_90", "form"],
            )
        )

    # -- comparison ---------------------------------------------------------------------------------

    async def match_comparison(self, match_id: int, premium: bool) -> MatchComparisonOut:
        """Cached per tier (not per user), so a plan change never serves stale access."""
        await self.form._match(match_id)  # 404 for an unknown match even on a cache hit
        if self.cache is None:
            return await self._match_comparison(match_id, premium)
        from app.core.redis_keys import RedisKeys

        return await self.cache.get_or_set_model(
            RedisKeys.match_comparison(match_id, "full" if premium else "basic"), MatchComparisonOut,
            lambda: self._match_comparison(match_id, premium), ttl_seconds=settings.analytics_cache_ttl_seconds,
        )

    async def _match_comparison(self, match_id: int, premium: bool) -> MatchComparisonOut:
        match = await self.form._match(match_id)
        window = 10 if premium else 5
        # Analytics going *into* the match: results strictly before kickoff, the match itself excluded.
        home = await self.compute_team_analytics(match.home_team_id, "overall", window, match.kickoff_time, match.id)
        away = await self.compute_team_analytics(match.away_team_id, "overall", window, match.kickoff_time, match.id)
        home_form = await self.form._compute_team_form(match.home_team_id, "overall", window, match.kickoff_time, match.id)
        away_form = await self.form._compute_team_form(match.away_team_id, "overall", window, match.kickoff_time, match.id)
        h2h = await self.form.get_head_to_head(match_id, "last5")

        def row(key, label, section, name, *, better: bool | None = True, premium_only: bool = False) -> ComparisonRow:
            h = getattr(home, section)[name]
            a = getattr(away, section)[name]
            return ComparisonRow(
                key=key, label=label, home=h.value, away=a.value, higher_is_better=better,
                home_sample=h.sample, away_sample=a.sample, premium=premium_only,
            )

        def rec(key, label, getter, *, better: bool | None = True) -> ComparisonRow:
            return ComparisonRow(
                key=key, label=label, home=getter(home_form.summary), away=getter(away_form.summary),
                higher_is_better=better, home_sample=home_form.summary.played, away_sample=away_form.summary.played,
            )

        rows = [
            rec("points_per_match", "Points per match", lambda s: s.ppg),
            rec("goals_for", "Goals scored per match", lambda s: s.goals_for_per_match),
            rec("goals_against", "Goals conceded per match", lambda s: s.goals_against_per_match, better=False),
            rec("clean_sheets", "Clean sheets", lambda s: float(s.clean_sheets)),
        ]
        locked: list[str] = []
        if premium:
            rows += [
                row("possession", "Possession %", "possession", "possession_pct", better=None, premium_only=True),
                row("shots", "Shots per match", "attack", "shots_per_match", premium_only=True),
                row("shots_on_target", "Shots on target", "attack", "shots_on_target", premium_only=True),
                row("xg", "Expected goals per match", "attack", "expected_goals_per_match", premium_only=True),
                row("pass_accuracy", "Pass accuracy %", "possession", "pass_accuracy_pct", premium_only=True),
                row("tackles", "Tackles", "defence", "tackles", premium_only=True),
                row("interceptions", "Interceptions", "defence", "interceptions", premium_only=True),
                row("yellow_cards", "Yellow cards", "discipline", "yellow_cards", better=False, premium_only=True),
                row("fouls", "Fouls", "discipline", "fouls", better=False, premium_only=True),
            ]
        else:
            locked = ["possession", "shots", "passing", "defence", "discipline", "expected_goals", "longer_form"]
        limitations = list(dict.fromkeys(home.limitations + away.limitations))
        return MatchComparisonOut(
            match_id=match_id,
            home_team=TeamOut.model_validate(match.home_team),
            away_team=TeamOut.model_validate(match.away_team),
            generated_at=datetime.now(timezone.utc),
            tier="full" if premium else "basic",
            form_window=window,
            home_form=home_form.summary,
            away_form=away_form.summary,
            home_sequence=home_form.sequence,
            away_sequence=away_form.sequence,
            head_to_head=h2h,
            rows=rows,
            locked=locked,
            limitations=limitations,
        )
