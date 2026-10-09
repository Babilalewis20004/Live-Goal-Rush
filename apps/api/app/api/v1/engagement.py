"""View tracking (discovery §27). One cheap Redis write; see
`services/engagement_service.py` for the pipeline and its privacy properties."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ArticleServiceDep, RedisServiceDep
from app.core.config import settings
from app.core.rate_limit import client_ip, rate_limiter
from app.db.session import get_db
from app.models.enums import EngagementEntity, EngagementSignal
from app.schemas.discovery import ViewTrackIn
from app.services.engagement_service import entity_exists, record_engagement, viewer_fingerprint

router = APIRouter()


@router.post(
    "/view",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limiter("track", settings.track_rate_limit_per_minute, 60))],
)
async def track_view(
    payload: ViewTrackIn,
    request: Request,
    redis: RedisServiceDep,
    articles: ArticleServiceDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Records that someone viewed an article/team/player/competition/match.
    Always answers 204 for a real entity: whether the view was *counted*
    (de-duplication, Redis availability) is deliberately not revealed."""
    entity_id = payload.entity_id
    if payload.entity_type == EngagementEntity.ARTICLE and entity_id is None and payload.slug:
        entity_id = await articles.public_id_for_slug(payload.slug)
    if entity_id is None or not await entity_exists(db, payload.entity_type, entity_id):
        raise HTTPException(status_code=404, detail="Nothing to track")
    viewer = viewer_fingerprint(
        client_ip(request), request.headers.get("user-agent")
    )
    await record_engagement(redis.raw, payload.entity_type, entity_id, EngagementSignal.VIEW, viewer)
