from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.competition import Competition
from app.models.match import Match
from app.services.article_seed import ensure_default_categories
from app.services.football_service import FootballService
from app.services.providers import get_provider


async def seed_database() -> None:
    """Warm the database with the provider's current competitions, teams,
    matches and standings on startup, so id-based lookups (GET /teams/{id},
    /competitions/{id}, ...) work immediately rather than 404ing until the
    Celery beat schedule's first sync cycle completes (see
    app/worker/schedule.py). Also makes sure the article categories exist
    (one per synced competition, plus a few generic ones).

    Skipped when the database was synced within `_FRESH_FOR` (Phase 7): every API process runs this on start,
    so without the check each restart, deploy or autoscale event spends a full round of the provider's daily
    request quota -- and a crash loop would exhaust it. The Celery sync jobs keep the data current either way."""
    async with AsyncSessionLocal() as db:
        if not await _recently_synced(db):
            service = FootballService(db=db, provider=get_provider())
            await service.sync_all_competitions_and_fixtures()
        await ensure_default_categories(db)


_FRESH_FOR = timedelta(hours=12)


async def _recently_synced(db) -> bool:
    if not await db.scalar(select(func.count()).select_from(Competition)):
        return False
    newest = await db.scalar(select(func.max(Match.last_synced_at)))
    return newest is not None and datetime.now(timezone.utc) - newest < _FRESH_FOR
