"""Stored match predictions and their evaluation (Phase 6b).

The model itself is `analytics_math.predict` -- a deterministic independent-
Poisson estimate. This service gathers its inputs from finished matches, stores
the result with the model version and data timestamp, locks it at kickoff so it
can later be judged fairly, and measures it against actual results.

These are statistical estimates, not advice, and nothing here claims accuracy
that has not been measured: `evaluation_summary` reports sample size and a
no-skill baseline alongside every score.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.redis_keys import RedisKeys
from app.events.community import publish_match_event
from app.events.schemas import RealtimeEventType
from app.models.analytics import Prediction, PredictionEvaluation
from app.models.enums import MatchStatus
from app.models.match import Match
from app.schemas.analytics import CalibrationBinOut, PredictionEvaluationSummary, PredictionOut
from app.services.analytics_math import (
    MODEL_VERSION,
    UNIFORM_BRIER,
    LeagueBaseline,
    TeamRecord,
    actual_outcome,
    brier_score,
    calibration_bins,
    predict,
)
from app.services.cache import CacheAside
from app.services.football_service import NotFoundError
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

LEAGUE_SAMPLE = 300
EVALUATION_NOTE = (
    "Scores are measured on matches the model predicted before kickoff. A small sample says little; "
    "compare with the baseline before reading anything into accuracy."
)


def influences_for(factors: dict) -> list[str]:
    """Plain-language description of what the estimate was built from -- only what the model really used."""
    return [
        f"Recent results of both teams (last {min(factors.get('home_matches', 0), factors.get('away_matches', 0))}"
        f"+ matches each, split by home and away)",
        "Goals scored and conceded compared with the league average",
        f"League scoring averages from {factors.get('league_matches', 0)} finished matches",
        "A home-advantage adjustment taken from those league averages",
    ]


class PredictionService:
    def __init__(self, db: AsyncSession, cache: CacheAside | None = None) -> None:
        self.db = db
        self.cache = cache

    async def _match(self, match_id: int) -> Match:
        m = (await self.db.execute(select(Match).where(Match.id == match_id).options(selectinload(Match.home_team), selectinload(Match.away_team)))).scalar_one_or_none()
        if m is None:
            raise NotFoundError(f"Match {match_id} not found")
        return m

    async def _record(self, team_id: int, before: datetime, exclude: int) -> tuple[TeamRecord, datetime | None]:
        rows = (
            await self.db.execute(
                select(Match)
                .where(
                    Match.status == MatchStatus.FINISHED,
                    Match.kickoff_time < before,
                    Match.id != exclude,
                    (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
                )
                .order_by(Match.kickoff_time.desc())
                .limit(settings.analytics_window_matches)
            )
        ).scalars().all()
        hf = ha = hp = af = aa = ap = 0
        for m in rows:
            if m.home_team_id == team_id:
                hf, ha, hp = hf + m.home_score, ha + m.away_score, hp + 1
            else:
                af, aa, ap = af + m.away_score, aa + m.home_score, ap + 1
        return TeamRecord(hf, ha, hp, af, aa, ap), (rows[0].kickoff_time if rows else None)

    async def _league(self, competition_id: int, before: datetime, exclude: int) -> LeagueBaseline:
        base = (
            select(Match.home_score, Match.away_score)
            .where(Match.status == MatchStatus.FINISHED, Match.kickoff_time < before, Match.id != exclude)
            .order_by(Match.kickoff_time.desc())
            .limit(LEAGUE_SAMPLE)
        )
        rows = (await self.db.execute(base.where(Match.competition_id == competition_id))).all()
        if len(rows) < 10:  # too few in this competition: fall back to every stored finished match
            rows = (await self.db.execute(base)).all()
        if len(rows) < 10:
            return LeagueBaseline(matches=len(rows))  # documented defaults
        return LeagueBaseline(
            home_goals=sum(r[0] for r in rows) / len(rows), away_goals=sum(r[1] for r in rows) / len(rows), matches=len(rows)
        )

    async def generate(self, match_id: int, *, now: datetime | None = None) -> PredictionOut:
        """Compute and store the estimate for an upcoming match (idempotent: same
        data -> same numbers; one row per match and model version). A match that
        has kicked off keeps whatever was stored -- predictions are never rewritten
        after the fact."""
        now = now or datetime.now(timezone.utc)
        match = await self._match(match_id)
        existing = await self._stored(match_id)
        if match.kickoff_time <= now or match.status != MatchStatus.SCHEDULED:
            if existing is not None:
                return self._to_out(existing, premium=True)
            return PredictionOut(match_id=match_id, status="unavailable", reason="Predictions are only made before kickoff.")

        home, home_ts = await self._record(match.home_team_id, match.kickoff_time, match.id)
        away, away_ts = await self._record(match.away_team_id, match.kickoff_time, match.id)
        league = await self._league(match.competition_id, match.kickoff_time, match.id)
        result = predict(home, away, league)
        if result is None:
            return PredictionOut(
                match_id=match_id, status="insufficient_data",
                reason="Not enough past results for both teams to make an estimate.",
            )
        stamps = [t for t in (home_ts, away_ts) if t is not None]
        data_ts = max(stamps) if stamps else None

        values = dict(
            match_id=match_id, model_version=MODEL_VERSION, home_win=result.home_win, draw=result.draw,
            away_win=result.away_win, expected_home_goals=result.expected_home_goals,
            expected_away_goals=result.expected_away_goals, expected_total_goals=result.expected_total_goals,
            confidence=result.confidence, confidence_score=result.confidence_score, factors=result.factors,
            data_timestamp=data_ts, generated_at=now,
        )
        stmt = pg_insert(Prediction).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_predictions_match_model",
            set_={k: v for k, v in values.items() if k not in ("match_id", "model_version")},
        ).returning(Prediction.id)
        pid = (await self.db.execute(stmt)).scalar_one()
        await self.db.commit()
        metrics.count("prediction_generation_total")
        if self.cache is not None:
            await self.cache.invalidate(RedisKeys.match_prediction(match_id))
            await publish_match_event(self.cache.redis, RealtimeEventType.PREDICTION_UPDATED, match_id, throttle=False)
        row = await self.db.get(Prediction, pid, populate_existing=True)
        return self._to_out(row, premium=True)

    async def _stored(self, match_id: int) -> Prediction | None:
        return (
            await self.db.execute(
                select(Prediction).where(Prediction.match_id == match_id, Prediction.model_version == MODEL_VERSION)
            )
        ).scalar_one_or_none()

    @staticmethod
    def _to_out(p: Prediction, premium: bool) -> PredictionOut:
        return PredictionOut(
            match_id=p.match_id, status="available", model_version=p.model_version, generated_at=p.generated_at,
            data_timestamp=p.data_timestamp, confidence=p.confidence,
            home_win=p.home_win, draw=p.draw, away_win=p.away_win, expected_total_goals=p.expected_total_goals,
            influences=influences_for(p.factors or {}),
            **(
                dict(
                    expected_home_goals=p.expected_home_goals, expected_away_goals=p.expected_away_goals,
                    confidence_score=p.confidence_score, factors=p.factors,
                )
                if premium
                else dict(locked=["expected_goals_by_team", "model_factors", "confidence_score"])
            ),
        )

    async def get(self, match_id: int, premium: bool) -> PredictionOut:
        """Read the stored estimate (never computes). The full object is cached once per
        match; the free view is derived from it after the cache, so a plan change can
        never serve the wrong breakdown."""
        await self._match(match_id)  # 404

        async def load() -> PredictionOut:
            stored = await self._stored(match_id)
            if stored is None:
                return PredictionOut(
                    match_id=match_id, status="unavailable",
                    reason="No estimate has been generated for this match yet.",
                )
            return self._to_out(stored, True)

        full = await load() if self.cache is None else await self.cache.get_or_set_model(
            RedisKeys.match_prediction(match_id), PredictionOut, load, ttl_seconds=settings.prediction_cache_ttl_seconds
        )
        return full if premium or full.status != "available" else self.shape_free(full)

    @staticmethod
    def shape_free(full: PredictionOut) -> PredictionOut:
        return full.model_copy(
            update=dict(
                expected_home_goals=None, expected_away_goals=None, confidence_score=None, factors=None,
                locked=["expected_goals_by_team", "model_factors", "confidence_score"],
            )
        )

    # -- batch jobs ---------------------------------------------------------------------------

    async def upcoming_match_ids(self, horizon_hours: int | None = None, now: datetime | None = None) -> list[int]:
        now = now or datetime.now(timezone.utc)
        end = now + timedelta(hours=horizon_hours or settings.prediction_horizon_hours)
        return list(
            (
                await self.db.execute(
                    select(Match.id).where(
                        Match.status == MatchStatus.SCHEDULED, Match.kickoff_time > now, Match.kickoff_time <= end
                    )
                )
            ).scalars()
        )

    async def evaluate_finished(self) -> int:
        """Score every stored prediction whose match has finished and has not been scored
        yet. Idempotent: the unique prediction_id means a second run adds nothing."""
        rows = (
            await self.db.execute(
                select(Prediction, Match)
                .join(Match, Match.id == Prediction.match_id)
                .outerjoin(PredictionEvaluation, PredictionEvaluation.prediction_id == Prediction.id)
                .where(Match.status == MatchStatus.FINISHED, PredictionEvaluation.id.is_(None))
            )
        ).all()
        created = 0
        for p, m in rows:
            actual = actual_outcome(m.home_score, m.away_score)
            predicted = max((("home", p.home_win), ("draw", p.draw), ("away", p.away_win)), key=lambda x: x[1])[0]
            stmt = (
                pg_insert(PredictionEvaluation)
                .values(
                    prediction_id=p.id, model_version=p.model_version, predicted_outcome=predicted,
                    actual_outcome=actual, correct=predicted == actual,
                    brier_score=brier_score(p.home_win, p.draw, p.away_win, actual), home_win=p.home_win,
                    total_goals_error=round(abs(p.expected_total_goals - (m.home_score + m.away_score)), 3),
                )
                .on_conflict_do_nothing(index_elements=["prediction_id"])
                .returning(PredictionEvaluation.id)
            )
            if (await self.db.execute(stmt)).scalar_one_or_none() is not None:
                created += 1
        await self.db.commit()
        if created:
            metrics.count("prediction_evaluation_total", created)
        return created

    async def evaluation_summary(self, model_version: str = MODEL_VERSION) -> PredictionEvaluationSummary:
        evs = (
            await self.db.execute(select(PredictionEvaluation).where(PredictionEvaluation.model_version == model_version))
        ).scalars().all()
        n = len(evs)
        if n == 0:
            return PredictionEvaluationSummary(
                model_version=model_version, evaluated=0, baseline_brier_score=UNIFORM_BRIER,
                note="No predictions have been evaluated yet, so no accuracy is claimed.",
            )
        mean_brier = round(sum(e.brier_score for e in evs) / n, 4)
        bins = calibration_bins((e.home_win, e.actual_outcome == "home") for e in evs)
        return PredictionEvaluationSummary(
            model_version=model_version,
            evaluated=n,
            accuracy=round(sum(e.correct for e in evs) / n, 4),
            mean_brier_score=mean_brier,
            baseline_brier_score=UNIFORM_BRIER,
            beats_baseline=mean_brier < UNIFORM_BRIER,
            mean_total_goals_error=round(sum(e.total_goals_error for e in evs) / n, 3),
            calibration_home_win=[CalibrationBinOut(**b.__dict__) for b in bins],
            note=EVALUATION_NOTE,
        )
