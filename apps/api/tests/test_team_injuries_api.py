"""GET /api/v1/teams/{id}/injuries: read-through to the provider."""

from datetime import datetime, timezone

import pytest

from app.api.deps import get_provider
from app.main import create_app  # noqa: F401  (client fixture builds the app)
from app.services.providers.base import ProviderQuotaExhausted
from app.services.providers.schemas import ProviderInjury, ProviderPlayer
from tests.fakes.mock_provider import MockFootballDataProvider


class _WithInjuries(MockFootballDataProvider):
    async def get_team_injuries(self, team_id):
        return [
            ProviderInjury(
                player=ProviderPlayer(provider_id="9", name="J. Doku"),
                kind="missing",
                reason="Calf Injury",
                match_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
            )
        ]


class _QuotaSpent(MockFootballDataProvider):
    async def get_team_injuries(self, team_id):
        raise ProviderQuotaExhausted("spent")


class _Broken(MockFootballDataProvider):
    async def get_team_injuries(self, team_id):
        raise RuntimeError("boom")


def _use(seeded_client, provider_cls):
    app = seeded_client._transport.app
    app.dependency_overrides[get_provider] = lambda: provider_cls()


async def test_unsupported_provider_says_so(seeded_client):
    resp = await seeded_client.get("/api/v1/teams/1/injuries")
    assert resp.status_code == 200
    assert resp.json() == {"supported": False, "items": []}


async def test_injuries_are_returned_when_supported(seeded_client):
    _use(seeded_client, _WithInjuries)
    body = (await seeded_client.get("/api/v1/teams/1/injuries")).json()

    assert body["supported"] is True
    assert body["items"][0]["player_name"] == "J. Doku"
    assert body["items"][0]["kind"] == "missing"
    assert body["items"][0]["reason"] == "Calf Injury"


@pytest.mark.parametrize("provider_cls", [_QuotaSpent, _Broken])
async def test_provider_failure_reads_as_no_known_injuries(seeded_client, provider_cls):
    _use(seeded_client, provider_cls)
    resp = await seeded_client.get("/api/v1/teams/1/injuries")

    assert resp.status_code == 200
    assert resp.json() == {"supported": True, "items": []}


async def test_unknown_team_is_404(seeded_client):
    assert (await seeded_client.get("/api/v1/teams/99999/injuries")).status_code == 404
