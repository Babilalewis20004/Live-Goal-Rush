from abc import ABC, abstractmethod
from datetime import date

from app.services.providers.schemas import (
    ProviderCompetition,
    ProviderMatch,
    ProviderSearchResult,
    ProviderStandingRow,
    ProviderTeam,
)


class FootballDataProvider(ABC):
    """Abstraction over an external football data source.

    The rest of the application (service layer, routers, web/mobile clients)
    depends only on this interface and never on a concrete provider, so a
    mock implementation and a real one are interchangeable without touching
    any other layer.
    """

    @abstractmethod
    async def get_live_matches(self) -> list[ProviderMatch]: ...

    @abstractmethod
    async def get_fixtures(self, on_date: date) -> list[ProviderMatch]: ...

    @abstractmethod
    async def get_match(self, match_id: str) -> ProviderMatch | None: ...

    @abstractmethod
    async def get_competitions(self) -> list[ProviderCompetition]: ...

    @abstractmethod
    async def get_competition_fixtures(self, competition_id: str) -> list[ProviderMatch]: ...

    @abstractmethod
    async def get_standings(self, competition_id: str) -> list[ProviderStandingRow]: ...

    @abstractmethod
    async def get_team(self, team_id: str) -> ProviderTeam | None: ...

    @abstractmethod
    async def get_team_fixtures(self, team_id: str) -> list[ProviderMatch]: ...

    @abstractmethod
    async def search(self, query: str) -> ProviderSearchResult: ...
