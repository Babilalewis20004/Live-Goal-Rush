"""Rate limits key on the real visitor, but `X-Forwarded-For` is only believed
from a configured trusted proxy -- otherwise anyone could dodge a limit by
inventing the header."""

from types import SimpleNamespace

from app.core.config import settings
from app.core.rate_limit import client_ip

API = "/api/v1"


def _request(peer: str | None, forwarded: str | None = None):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer) if peer else None, headers=headers)


def test_forwarded_for_is_ignored_unless_the_peer_is_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "")
    assert client_ip(_request("203.0.113.5", "198.51.100.7")) == "203.0.113.5"
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    assert client_ip(_request("203.0.113.5", "198.51.100.7")) == "203.0.113.5"  # peer not in range: spoof ignored
    assert client_ip(_request("10.1.2.3", "198.51.100.7, 10.1.2.3")) == "198.51.100.7"  # trusted: first hop


def test_garbage_is_never_used_as_an_address(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8, not-a-cidr")
    assert client_ip(_request("10.1.2.3", "'; DROP TABLE x;--")) == "10.1.2.3"
    assert client_ip(_request("10.1.2.3", None)) == "10.1.2.3"
    assert client_ip(_request(None)) == "unknown"
    assert client_ip(_request("not-an-ip", "198.51.100.7")) == "not-an-ip"
    assert client_ip(_request("10.1.2.3", "2001:db8::1")) == "2001:db8::1"


async def test_rate_limit_counts_each_forwarded_visitor_separately_only_behind_a_trusted_proxy(client, monkeypatch):
    limit = settings.search_rate_limit_per_minute
    # Untrusted peer: the header is ignored, so one client making many requests is limited.
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "")
    codes = [
        (await client.get(f"{API}/search", params={"q": ""}, headers={"x-forwarded-for": f"198.51.100.{i % 250 + 1}"})).status_code
        for i in range(limit + 1)
    ]
    assert codes[-1] == 429


async def test_trusted_proxy_lets_many_real_visitors_through(client, monkeypatch):
    limit = settings.search_rate_limit_per_minute
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "127.0.0.0/8")
    codes = [
        (await client.get(f"{API}/search", params={"q": ""}, headers={"x-forwarded-for": f"198.51.100.{i % 250 + 1}"})).status_code
        for i in range(limit + 5)
    ]
    assert set(codes) == {200}  # each visitor has their own budget
