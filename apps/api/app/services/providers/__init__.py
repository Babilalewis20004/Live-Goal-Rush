from functools import lru_cache

from app.core.config import settings
from app.services.providers.base import FootballDataProvider
from app.services.providers.mock_provider import MockFootballDataProvider
from app.services.providers.real_provider import RealFootballDataProvider


@lru_cache
def get_provider() -> FootballDataProvider:
    """Provider factory. The rest of the app depends only on the abstract
    `FootballDataProvider` interface and never knows which concrete
    implementation is active."""
    if settings.football_data_provider == "real":
        return RealFootballDataProvider(
            base_url=settings.football_api_base_url,
            api_key=settings.football_api_key,
            features=settings.football_api_features,
        )
    return MockFootballDataProvider()
