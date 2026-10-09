from functools import lru_cache

from app.core.config import settings
from app.services.providers.api_football_provider import ApiFootballProvider
from app.services.providers.base import FootballDataProvider
from app.services.providers.real_provider import RealFootballDataProvider


@lru_cache
def get_provider() -> FootballDataProvider:
    """Provider factory. The rest of the app depends only on the abstract
    `FootballDataProvider` interface and never knows which concrete
    implementation is active."""
    if settings.football_data_provider == "api-football":
        return ApiFootballProvider(
            api_key=settings.football_api_key,
            base_url=settings.football_api_base_url,
            league_ids=settings.football_api_league_ids or None,
        )
    if settings.football_data_provider == "real":
        return RealFootballDataProvider(
            base_url=settings.football_api_base_url,
            api_key=settings.football_api_key,
            features=settings.football_api_features,
        )
    raise RuntimeError(
        f"Unknown FOOTBALL_DATA_PROVIDER={settings.football_data_provider!r}; "
        "use 'api-football' or 'real'."
    )
