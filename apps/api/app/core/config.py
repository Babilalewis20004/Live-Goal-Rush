from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application configuration.

    All values have safe local-dev defaults so the app can boot without a
    `.env` file; real deployments must override via environment variables.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = (
        "postgresql+asyncpg://football:football@localhost:5432/football_livescore"
    )

    # Football data provider abstraction (see app/services/providers).
    football_data_provider: str = "mock"  # "mock" | "real"
    football_api_base_url: str = ""
    football_api_key: str = ""

    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
