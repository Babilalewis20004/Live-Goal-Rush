"""Provider rate-limit protection (Phase 2 §10).

Every provider call the worker makes goes through `call_with_backoff`,
which tracks request/error/429 counts (spec §27's
`provider_requests_total`/`provider_errors_total`) and retries with
exponential backoff -- explicitly not retrying immediately on a 429 --
up to `SYNC_MAX_RETRIES` before giving up on that sync cycle.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from app.core.config import settings
from app.services.providers.base import FootballDataProvider
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ProviderUnavailableError(Exception):
    """Raised when a provider call exhausts its retries. Sync tasks catch
    this, log it, and skip that cycle rather than crash the worker process
    or propagate a 500 to any client (spec §22)."""


async def call_with_backoff(operation: str, fn: Callable[[], Awaitable[T]]) -> T:
    attempt = 0
    while True:
        attempt += 1
        metrics.provider_request()
        try:
            return await fn()
        except httpx.HTTPStatusError as exc:
            metrics.provider_error()
            if exc.response.status_code == 429:
                metrics.provider_rate_limited()
                logger.warning("Provider rate-limited on %s (attempt %d)", operation, attempt)
            else:
                logger.warning("Provider error on %s: %s (attempt %d)", operation, exc, attempt)
        except Exception:
            metrics.provider_error()
            logger.warning("Provider call failed on %s (attempt %d)", operation, attempt, exc_info=True)

        if attempt >= settings.sync_max_retries:
            raise ProviderUnavailableError(f"{operation} failed after {attempt} attempt(s)")

        backoff_seconds = settings.sync_backoff_seconds * (2 ** (attempt - 1))
        logger.info("Backing off %.1fs before retrying %s (attempt %d)", backoff_seconds, operation, attempt)
        await asyncio.sleep(backoff_seconds)


class GuardedProvider(FootballDataProvider):
    """Wraps a provider so every call goes through `call_with_backoff`
    (Phase 2 §10) -- used by the Phase 4 sync code, which lives in the
    service layer and so can't call the worker's guard itself. A call that
    exhausts its retries raises `ProviderUnavailableError`, which the
    worker tasks catch per cycle."""

    def __init__(self, inner: FootballDataProvider) -> None:
        self._inner = inner

    @property
    def capabilities(self):
        return self._inner.capabilities

    async def get_live_matches(self):
        return await call_with_backoff("get_live_matches", self._inner.get_live_matches)

    async def get_fixtures(self, on_date):
        return await call_with_backoff(f"get_fixtures({on_date})", lambda: self._inner.get_fixtures(on_date))

    async def get_match(self, match_id):
        return await call_with_backoff(f"get_match({match_id})", lambda: self._inner.get_match(match_id))

    async def get_competitions(self):
        return await call_with_backoff("get_competitions", self._inner.get_competitions)

    async def get_competition_fixtures(self, competition_id):
        return await call_with_backoff(
            f"get_competition_fixtures({competition_id})",
            lambda: self._inner.get_competition_fixtures(competition_id),
        )

    async def get_standings(self, competition_id):
        return await call_with_backoff(
            f"get_standings({competition_id})", lambda: self._inner.get_standings(competition_id)
        )

    async def get_team(self, team_id):
        return await call_with_backoff(f"get_team({team_id})", lambda: self._inner.get_team(team_id))

    async def get_team_fixtures(self, team_id):
        return await call_with_backoff(
            f"get_team_fixtures({team_id})", lambda: self._inner.get_team_fixtures(team_id)
        )

    async def search(self, query):
        return await call_with_backoff("search", lambda: self._inner.search(query))

    async def get_lineups(self, match_id):
        return await call_with_backoff(f"get_lineups({match_id})", lambda: self._inner.get_lineups(match_id))

    async def get_match_statistics(self, match_id):
        return await call_with_backoff(
            f"get_match_statistics({match_id})", lambda: self._inner.get_match_statistics(match_id)
        )

    async def get_player_statistics(self, match_id):
        return await call_with_backoff(
            f"get_player_statistics({match_id})", lambda: self._inner.get_player_statistics(match_id)
        )

    async def get_team_squad(self, team_id):
        return await call_with_backoff(f"get_team_squad({team_id})", lambda: self._inner.get_team_squad(team_id))

    async def get_player(self, player_id):
        return await call_with_backoff(f"get_player({player_id})", lambda: self._inner.get_player(player_id))

    async def get_top_scorers(self, competition_id):
        return await call_with_backoff(
            f"get_top_scorers({competition_id})", lambda: self._inner.get_top_scorers(competition_id)
        )
