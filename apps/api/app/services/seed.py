from app.db.session import AsyncSessionLocal
from app.services.football_service import FootballService
from app.services.providers import get_provider


async def seed_database() -> None:
    """Warm the database with the provider's current competitions, teams and
    matches on startup. Phase 1 has no background ingestion job, so without
    this, id-based lookups (GET /teams/{id}, /competitions/{id}, ...) would
    404 until some earlier list request happened to sync that entity."""
    async with AsyncSessionLocal() as db:
        service = FootballService(db=db, provider=get_provider())
        await service.sync_all_competitions_and_fixtures()
