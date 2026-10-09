from abc import ABC, abstractmethod
from datetime import date

from app.services.providers.schemas import (
    ProviderCapabilities,
    ProviderCompetition,
    ProviderInjury,
    ProviderLineup,
    ProviderMatch,
    ProviderPlayer,
    ProviderPlayerMatchStatistics,
    ProviderSearchResult,
    ProviderStandingRow,
    ProviderTeam,
    ProviderTeamMatchStatistics,
    ProviderTopScorer,
)


class ProviderQuotaExhausted(Exception):
    """The provider's request quota is (nearly) spent. Not retried: another
    attempt would only spend more of it."""


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

    # -- Phase 4: optional capabilities -------------------------------------
    #
    # Deliberately *not* abstract: a provider implements only what it can
    # genuinely supply and declares that in `capabilities`. The defaults
    # below are "not supported", so callers must check `capabilities` (the
    # sync layer does) rather than assume data exists. Normalization into
    # the `Provider*` DTOs happens inside each implementation -- nothing
    # above this interface ever sees a provider's raw field names.

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    async def get_lineups(self, match_id: str) -> list[ProviderLineup]:
        return []

    async def get_match_statistics(self, match_id: str) -> list[ProviderTeamMatchStatistics]:
        return []

    async def get_player_statistics(self, match_id: str) -> list[ProviderPlayerMatchStatistics]:
        return []

    async def get_team_squad(self, team_id: str) -> list[ProviderPlayer]:
        return []

    async def get_player(self, player_id: str) -> ProviderPlayer | None:
        return None

    async def get_top_scorers(self, competition_id: str) -> list[ProviderTopScorer]:
        return []

    async def get_team_injuries(self, team_id: str) -> list[ProviderInjury]:
        """Current injuries / doubts for a team. Default: unsupported."""
        return []

    async def get_historical_standings(self, competition_id: str, season: str) -> list[ProviderStandingRow]:
        """Standings for a past `season` label (Phase 5). Default: unsupported."""
        return []

    async def get_historical_top_scorers(self, competition_id: str, season: str) -> list[ProviderTopScorer]:
        return []
