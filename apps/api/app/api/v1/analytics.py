"""Analytics, comparison, predictions and persisted insights (Phase 6b).

Access is decided here, on the server, from the caller's real entitlements:

* The basic view is public and useful on its own (results, goals, clean sheets,
  5-match form, the prediction headline).
* Premium widens it. Where a request asks for something only Premium has (a
  longer window), it gets 402 naming the entitlement; where the same endpoint
  can serve a smaller answer (analytics sections), it returns the basic shape
  and lists what was withheld in `locked`.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.core.rate_limit import rate_limiter

from app.api.deps import (
    AnalyticsServiceDep,
    CurrentUserDep,
    EntitlementsDep,
    FootballServiceDep,
    FormServiceDep,
    InsightsServiceDep,
    PredictionServiceDep,
    TeamPlayerServiceDep,
    require_entitlement,
)
from app.db.session import get_db
from app.models.enums import InsightEntityType
from app.schemas.analytics import (
    InsightRecordOut,
    MatchComparisonOut,
    PlayerAnalyticsOut,
    PredictionEvaluationSummary,
    PredictionOut,
    TeamAnalyticsOut,
)
from app.schemas.form import HeadToHeadOut, TeamFormOut
from app.services import personal_insights
from app.services.analytics_service import FREE_MAX_WINDOW, WINDOWS
from app.services.billing import entitlements as ent
from app.services.football_service import NotFoundError
from app.services.insight_records import InsightGenerator
from app.services.metrics import metrics

def _check_window(window: int) -> None:
    if window not in WINDOWS:
        raise HTTPException(status_code=422, detail=f"window must be one of {list(WINDOWS)}")


teams_router = APIRouter()
players_router = APIRouter()
matches_router = APIRouter()
predictions_router = APIRouter()
me_router = APIRouter()


# -- teams -----------------------------------------------------------------------------------------


@teams_router.get(
    "/{team_id}/analytics",
    response_model=TeamAnalyticsOut,
    dependencies=[Depends(rate_limiter("analytics-team", settings.analytics_per_minute, 60))],
)
async def team_analytics(
    team_id: int,
    service: AnalyticsServiceDep,
    ents: EntitlementsDep,
    scope: Literal["overall", "home", "away"] = "overall",
    window: int = 10,
) -> TeamAnalyticsOut:
    _check_window(window)
    if window > FREE_MAX_WINDOW:
        require_entitlement(ents, ent.EXTENDED_HISTORY)
    try:
        full = await service.team_analytics(team_id, scope, window)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc
    premium = ent.ADVANCED_ANALYTICS in ents
    metrics.count("premium_feature_usage_total" if premium else "premium_feature_denied_total")
    return service.shape_team(full, premium)


@teams_router.get("/{team_id}/form/extended", response_model=TeamFormOut)
async def team_form_extended(
    team_id: int,
    teams: FootballServiceDep,
    service: FormServiceDep,
    ents: EntitlementsDep,
    scope: Literal["overall", "home", "away"] = "overall",
    limit: int = 10,
) -> TeamFormOut:
    if limit not in (5, 10):
        raise HTTPException(status_code=422, detail="limit must be 5 or 10")
    """Last-10 form (Premium). The last-5 view stays at `/teams/{id}/form`."""
    if limit > 5:
        require_entitlement(ents, ent.EXTENDED_HISTORY)
    try:
        await teams.get_team(team_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc
    return await service.get_team_form(team_id, scope, limit)


@teams_router.get("/{team_id}/insight-records", response_model=list[InsightRecordOut])
async def team_insight_records(team_id: int, teams: FootballServiceDep, db=Depends(get_db)) -> list[InsightRecordOut]:
    try:
        await teams.get_team(team_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Team not found") from exc
    return await _records(db, InsightEntityType.TEAM, team_id)


# -- players ----------------------------------------------------------------------------------------


@players_router.get(
    "/{player_id}/analytics",
    response_model=PlayerAnalyticsOut,
    dependencies=[Depends(rate_limiter("analytics-player", settings.analytics_per_minute, 60))],
)
async def player_analytics(
    player_id: int,
    service: AnalyticsServiceDep,
    ents: EntitlementsDep,
    window: int = 10,
) -> PlayerAnalyticsOut:
    _check_window(window)
    if window > FREE_MAX_WINDOW:
        require_entitlement(ents, ent.EXTENDED_HISTORY)
    try:
        full = await service.player_analytics(player_id, window)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Player not found") from exc
    premium = ent.PLAYER_ANALYTICS in ents
    metrics.count("premium_feature_usage_total" if premium else "premium_feature_denied_total")
    return service.shape_player(full, premium)


@players_router.get("/{player_id}/insights", response_model=list[InsightRecordOut])
async def player_insights(player_id: int, players: TeamPlayerServiceDep, db=Depends(get_db)) -> list[InsightRecordOut]:
    try:
        await players.get_player(player_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Player not found") from exc
    return await _records(db, InsightEntityType.PLAYER, player_id)


# -- matches ------------------------------------------------------------------------------------------


@matches_router.get(
    "/{match_id}/comparison",
    response_model=MatchComparisonOut,
    dependencies=[Depends(rate_limiter("analytics-comparison", settings.analytics_per_minute, 60))],
)
async def match_comparison(match_id: int, service: AnalyticsServiceDep, ents: EntitlementsDep) -> MatchComparisonOut:
    premium = ent.ADVANCED_COMPARISON in ents
    try:
        out = await service.match_comparison(match_id, premium)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc
    metrics.count("premium_feature_usage_total" if premium else "premium_feature_denied_total")
    return out


@matches_router.get("/{match_id}/prediction", response_model=PredictionOut)
async def match_prediction(match_id: int, service: PredictionServiceDep, ents: EntitlementsDep) -> PredictionOut:
    """The stored model estimate (generated by a background job before kickoff).
    Labelled as an estimate; never a guarantee."""
    try:
        return await service.get(match_id, ent.PREDICTION_DETAILS in ents)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@matches_router.get("/{match_id}/head-to-head/extended", response_model=HeadToHeadOut)
async def head_to_head_extended(
    match_id: int,
    service: FormServiceDep,
    ents: EntitlementsDep,
    window: Literal["last5", "last10", "all"] = "last10",
) -> HeadToHeadOut:
    """Longer head-to-head windows (Premium). Last 5 stays at `/matches/{id}/head-to-head`."""
    if window != "last5":
        require_entitlement(ents, ent.EXTENDED_HISTORY)
    try:
        return await service.get_head_to_head(match_id, window)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc


@matches_router.get("/{match_id}/insight-records", response_model=list[InsightRecordOut])
async def match_insight_records(match_id: int, matches: FootballServiceDep, db=Depends(get_db)) -> list[InsightRecordOut]:
    try:
        await matches.get_match(match_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match not found") from exc
    return await _records(db, InsightEntityType.MATCH, match_id)


# -- evaluation (public, honest) -----------------------------------------------------------------------


@predictions_router.get("/evaluation", response_model=PredictionEvaluationSummary)
async def prediction_evaluation(service: PredictionServiceDep, model_version: str | None = None) -> PredictionEvaluationSummary:
    from app.services.analytics_math import MODEL_VERSION

    return await service.evaluation_summary(model_version or MODEL_VERSION)


# -- the signed-in user's own insights ----------------------------------------------------------------


@me_router.get("/insights", response_model=list[personal_insights.PersonalInsight])
async def my_insights(user: CurrentUserDep, db=Depends(get_db)) -> list[personal_insights.PersonalInsight]:
    return await personal_insights.for_user(db, user.id)


async def _records(db, entity: InsightEntityType, entity_id: int) -> list[InsightRecordOut]:
    rows = await InsightGenerator(db).read(entity, entity_id)
    return [
        InsightRecordOut(
            entity_type=r.entity_type.value, entity_id=r.entity_id, insight_type=r.insight_type, text=r.text,
            value=r.value, source_data_version=r.source_data_version, generated_at=r.generated_at,
        )
        for r in rows
    ]
