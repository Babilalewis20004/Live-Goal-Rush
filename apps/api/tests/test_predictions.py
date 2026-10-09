"""Stored predictions, locking, shaping and evaluation (Phase 6b)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.models.analytics import Prediction, PredictionEvaluation
from app.models.billing import Entitlement
from app.models.enums import MatchStatus
from app.models.match import Match
from app.services.analytics_math import MODEL_VERSION, UNIFORM_BRIER
from app.services.billing import entitlements as ent
from app.services.prediction_service import PredictionService
from app.worker.analytics_tasks import generate_predictions_once
from tests.football_data import NOW, make_competition, make_match, make_team

API = "/api/v1"


@pytest.fixture
async def world(session_factory):
    comp = await make_competition(session_factory)
    strong, weak, mid = [await make_team(session_factory, n) for n in ("Strong FC", "Weak FC", "Mid FC")]
    newbie = await make_team(session_factory, "Newbie FC")
    # Strong: wins big home and away; Weak: loses everywhere; Mid: in between. Six matches each against Mid.
    for i in range(6):
        if i % 2 == 0:
            await make_match(session_factory, comp, strong, mid, 60 - i * 5, 3, 0)  # Strong wins at home
            await make_match(session_factory, comp, weak, mid, 58 - i * 5, 0, 2)  # Weak loses at home
        else:
            await make_match(session_factory, comp, mid, strong, 60 - i * 5, 0, 2)  # Strong wins away
            await make_match(session_factory, comp, mid, weak, 58 - i * 5, 3, 0)  # Weak loses away
    fixture = await make_match(session_factory, comp, strong, weak, -1, status=MatchStatus.SCHEDULED)
    no_history = await make_match(session_factory, comp, newbie, mid, -1, status=MatchStatus.SCHEDULED)
    return dict(comp=comp, strong=strong, weak=weak, mid=mid, newbie=newbie, fixture=fixture, no_history=no_history)


async def test_generation_stores_a_versioned_reproducible_estimate(session_factory, world):
    async with session_factory() as db:
        service = PredictionService(db)
        first = await service.generate(world["fixture"])
        assert first.status == "available" and first.model_version == MODEL_VERSION
        assert first.home_win > first.draw and first.home_win > first.away_win
        assert first.home_win + first.draw + first.away_win == pytest.approx(1.0, abs=2e-4)
        assert first.data_timestamp is not None and first.generated_at is not None and first.confidence in ("low", "medium", "high")
        assert first.label == "Model estimate" and "not betting advice" in first.disclaimer
        second = await service.generate(world["fixture"])
        assert (second.home_win, second.draw, second.away_win) == (first.home_win, first.draw, first.away_win)  # same data -> same numbers
        assert await db.scalar(select(func.count()).select_from(Prediction)) == 1  # upserted, not duplicated


async def test_not_enough_history_means_no_prediction_not_a_guess(session_factory, world):
    async with session_factory() as db:
        out = await PredictionService(db).generate(world["no_history"])
        assert out.status == "insufficient_data" and "Not enough" in out.reason
        assert await db.scalar(select(func.count()).select_from(Prediction)) == 0


async def test_a_started_match_is_never_predicted_or_rewritten(session_factory, world):
    async with session_factory() as db:
        service = PredictionService(db)
        stored = await service.generate(world["fixture"])
        # after kickoff the stored estimate is returned untouched, even if the data changed since
        await make_match(session_factory, world["comp"], world["weak"], world["mid"], 1, 5, 0)
        later = await service.generate(world["fixture"], now=NOW + timedelta(days=2))
        assert later.home_win == stored.home_win and later.generated_at == stored.generated_at
        # and a match that kicked off without ever having one stays without
        none = await service.generate(world["no_history"], now=NOW + timedelta(days=2))
        assert none.status == "unavailable" and "before kickoff" in none.reason


async def test_endpoint_labels_it_an_estimate_and_free_users_get_the_headline_only(client, session_factory, world, make_user):
    async with session_factory() as db:
        await PredictionService(db).generate(world["fixture"])
    free = (await client.get(f"{API}/matches/{world['fixture']}/prediction")).json()
    assert free["status"] == "available" and free["label"] == "Model estimate"
    assert free["home_win"] is not None and free["expected_total_goals"] is not None
    assert free["expected_home_goals"] is None and free["factors"] is None and free["confidence_score"] is None
    assert "expected_goals_by_team" in free["locked"]
    assert any("Recent results" in i for i in free["influences"])
    assert not any("head-to-head" in i.lower() or "historical meetings" in i.lower() for i in free["influences"])  # only what the model really uses

    user, headers = await make_user("prem@example.com")
    async with session_factory() as db:
        db.add(Entitlement(user_id=user.id, key=ent.PREDICTION_DETAILS, source="test"))
        await db.commit()
    full = (await client.get(f"{API}/matches/{world['fixture']}/prediction", headers=headers)).json()
    assert full["expected_home_goals"] > full["expected_away_goals"] and full["factors"]["home_matches"] > 0 and full["locked"] == []
    assert (await client.get(f"{API}/matches/{world['fixture']}/prediction")).json()["factors"] is None  # cache is not per user


async def test_unpredicted_and_unknown_matches(client, world):
    body = (await client.get(f"{API}/matches/{world['no_history']}/prediction")).json()
    assert body["status"] == "unavailable" and body["home_win"] is None
    assert (await client.get(f"{API}/matches/999999/prediction")).status_code == 404


async def test_evaluation_scores_finished_matches_once(session_factory, client, world):
    async with session_factory() as db:
        service = PredictionService(db)
        await service.generate(world["fixture"])
        assert await service.evaluate_finished() == 0  # not finished yet
        await db.execute(update(Match).where(Match.id == world["fixture"]).values(status=MatchStatus.FINISHED, home_score=2, away_score=0))
        await db.commit()
        assert await service.evaluate_finished() == 1
        assert await service.evaluate_finished() == 0  # idempotent
        ev = (await db.execute(select(PredictionEvaluation))).scalar_one()
        assert ev.actual_outcome == "home" and ev.predicted_outcome == "home" and ev.correct
        assert 0 <= ev.brier_score < UNIFORM_BRIER  # a sensible call beats "no skill"
    summary = (await client.get(f"{API}/predictions/evaluation")).json()
    assert summary["evaluated"] == 1 and summary["accuracy"] == 1.0 and summary["beats_baseline"] is True
    assert summary["baseline_brier_score"] == pytest.approx(0.6667, abs=1e-4)
    assert "small sample" in summary["note"].lower()
    assert sum(b["count"] for b in summary["calibration_home_win"]) == 1


async def test_no_accuracy_is_claimed_without_evidence(client):
    body = (await client.get(f"{API}/predictions/evaluation")).json()
    assert body["evaluated"] == 0 and body["accuracy"] is None and body["mean_brier_score"] is None and body["beats_baseline"] is None
    assert "no accuracy is claimed" in body["note"]


async def test_the_scheduled_job_predicts_only_upcoming_matches_in_the_horizon_and_is_idempotent(session_factory, world, fake_redis):
    far = await make_match(session_factory, world["comp"], world["strong"], world["mid"], -30, status=MatchStatus.SCHEDULED)
    async with session_factory() as db:
        created = await generate_predictions_once(db)
        assert created == [world["fixture"]]  # the far fixture is beyond the horizon; Newbie has no history
        assert await generate_predictions_once(db) == []  # nothing new the second time
        assert await db.scalar(select(func.count()).select_from(Prediction)) == 1
    assert far


async def test_realtime_nudge_is_published_for_the_match_only(session_factory, world, fake_redis):
    from app.core.redis_keys import RedisKeys
    from app.services.cache import CacheAside

    pubsub = fake_redis.raw.pubsub()
    await pubsub.subscribe(RedisKeys.MATCH_EVENTS_CHANNEL)
    await pubsub.get_message(timeout=0.1)
    async with session_factory() as db:
        await PredictionService(db, CacheAside(fake_redis)).generate(world["fixture"])
    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
    assert message is not None and '"prediction.updated"' in message["data"] and f'"{world["fixture"]}"' in message["data"]
