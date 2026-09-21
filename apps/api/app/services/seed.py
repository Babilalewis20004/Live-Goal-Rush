from app.db.session import AsyncSessionLocal
from app.services.football_service import FootballService
from app.services.providers import get_provider


async def seed_database() -> None:
    """Warm the database with the provider's current competitions, teams,
    matches and standings on startup, so id-based lookups (GET /teams/{id},
    /competitions/{id}, ...) work immediately rather than 404ing until the
    Celery beat schedule's first sync cycle completes (see
    app/worker/schedule.py)."""
    async with AsyncSessionLocal() as db:
        service = FootballService(db=db, provider=get_provider())
        await service.sync_all_competitions_and_fixtures()
