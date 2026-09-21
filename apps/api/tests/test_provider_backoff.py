"""Provider rate-limit protection (Phase 2 §10): retries with exponential
backoff, explicit 429 tracking, and giving up after SYNC_MAX_RETRIES
rather than retrying forever."""

import httpx
import pytest

from app.services.metrics import metrics
from app.worker.provider_guard import ProviderUnavailableError, call_with_backoff


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Records sleep durations instead of actually waiting, so exponential
    growth can be asserted without a slow test."""
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.worker.provider_guard.asyncio.sleep", _fake_sleep)
    return sleeps


async def test_success_on_first_attempt_does_not_retry(_fast_backoff):
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return "ok"

    result = await call_with_backoff("test-op", fn)
    assert result == "ok"
    assert calls == 1
    assert _fast_backoff == []


async def test_exhausting_retries_raises_provider_unavailable(_fast_backoff):
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise ConnectionError("boom")

    with pytest.raises(ProviderUnavailableError):
        await call_with_backoff("test-op", fn)

    assert calls == 3  # settings.sync_max_retries default


async def test_backoff_grows_exponentially_between_attempts(_fast_backoff):
    async def fn():
        raise ConnectionError("boom")

    with pytest.raises(ProviderUnavailableError):
        await call_with_backoff("test-op", fn)

    # sync_backoff_seconds default is 5: attempt 1 -> 5s, attempt 2 -> 10s.
    assert _fast_backoff == [5, 10]


async def test_429_is_tracked_and_does_not_retry_immediately(_fast_backoff):
    before = metrics.snapshot()["provider_rate_limited_total"]

    async def fn():
        response = httpx.Response(status_code=429, request=httpx.Request("GET", "http://example.com"))
        raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)

    with pytest.raises(ProviderUnavailableError):
        await call_with_backoff("test-op", fn)

    after = metrics.snapshot()["provider_rate_limited_total"]
    assert after == before + 3  # one per attempt
    assert _fast_backoff == [5, 10]  # backed off between attempts, not immediate retries
