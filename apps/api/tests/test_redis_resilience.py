"""A Redis that is gone -- or worse, a Redis that accepts connections and never answers -- must not take the API with it.

Found in Phase 7 by stopping the Redis container under a running stack: every request that touched Redis hung (redis-py had no
timeouts), and the metrics sink flushed to Redis *synchronously on the event loop*, so a hung Redis froze the whole process,
liveness probe included.
"""

import asyncio
import threading
import time

import pytest
from httpx import ASGITransport, AsyncClient
from redis import exceptions as redis_exceptions

from app.core.redis_client import COMMAND_TIMEOUT_SECONDS, CircuitBreaker, RedisService
from app.services.metrics_aggregation import RedisMetricsSink


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_the_breaker_opens_on_failure_and_closes_after_its_window():
    clock = Clock()
    breaker = CircuitBreaker(open_seconds=5, clock=clock)
    breaker.before_call()  # closed: allowed
    breaker.record_failure()
    with pytest.raises(redis_exceptions.ConnectionError):
        breaker.before_call()
    clock.now += 4.9
    with pytest.raises(redis_exceptions.ConnectionError):
        breaker.before_call()
    clock.now += 0.2
    breaker.before_call()  # window over: the next call is the probe
    breaker.record_success()
    breaker.before_call()


class FlakyClient:
    def __init__(self):
        self.calls = 0
        self.down = True

    async def get(self, key):
        self.calls += 1
        if self.down:
            raise redis_exceptions.ConnectionError("refused")
        return '{"ok": true}'


async def test_after_one_failure_redis_calls_fail_instantly_until_the_probe_succeeds():
    clock, client = Clock(), FlakyClient()
    service = RedisService("redis://unused", client=client)
    service.breaker = CircuitBreaker(open_seconds=5, clock=clock)

    with pytest.raises(redis_exceptions.ConnectionError):
        await service.get("a")
    assert client.calls == 1
    for _ in range(50):  # a burst of requests during the outage: none of them touches the network
        with pytest.raises(redis_exceptions.ConnectionError):
            await service.get("a")
    assert client.calls == 1

    clock.now += 6
    client.down = False
    assert await service.get("a") == {"ok": True}  # the probe succeeded: traffic flows again
    assert await service.get("a") == {"ok": True}
    assert client.calls == 3


async def test_application_errors_do_not_open_the_breaker():
    class Corrupt:
        async def get(self, key):
            return "{not json"

    service = RedisService("redis://unused", client=Corrupt())
    with pytest.raises(ValueError):
        await service.get("a")
    assert not service.breaker.is_open


@pytest.fixture
async def black_hole():
    """A TCP port that accepts connections and never says anything: how an unreachable or wedged Redis behaves."""
    connections = []

    async def handler(reader, writer):
        connections.append(writer)
        await asyncio.sleep(3600)

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    yield port
    for writer in connections:
        writer.close()
    server.close()


async def test_a_redis_that_never_answers_times_out_and_does_not_stall_the_event_loop(black_hole):
    service = RedisService(f"redis://127.0.0.1:{black_hole}/0")
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    task = asyncio.create_task(ticker())
    started = time.monotonic()
    with pytest.raises((redis_exceptions.TimeoutError, redis_exceptions.ConnectionError)):
        await service.get("anything")
    elapsed = time.monotonic() - started
    task.cancel()
    assert elapsed < COMMAND_TIMEOUT_SECONDS + 1.5, f"took {elapsed:.1f}s"
    assert ticks >= 20, f"the event loop only ran {ticks} times while waiting: something blocked it"
    # and the next ones are instant
    started = time.monotonic()
    with pytest.raises(redis_exceptions.ConnectionError):
        await service.get("anything")
    assert time.monotonic() - started < 0.05
    await service.aclose()


async def test_the_api_stays_responsive_and_serves_reads_while_redis_is_wedged(black_hole, test_engine, memory_storage):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.api.deps import get_storage_dep
    from app.core.redis_client import get_redis_service
    from app.db.session import get_db
    from app.main import create_app
    from app.services.football_service import FootballService
    from app.services.providers import get_provider
    from tests.fakes.mock_provider import MockFootballDataProvider

    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as db:
        await FootballService(db=db, provider=MockFootballDataProvider()).sync_all_competitions_and_fixtures()

    wedged = RedisService(f"redis://127.0.0.1:{black_hole}/0")

    async def _db():
        async with session_local() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_provider] = lambda: MockFootballDataProvider()
    app.dependency_overrides[get_redis_service] = lambda: wedged
    app.dependency_overrides[get_storage_dep] = lambda: memory_storage
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30) as client:
        # the first request pays the connection timeouts once ...
        first = await client.get("/api/v1/matches/upcoming")
        assert first.status_code == 200
        # ... after which the breaker is open: reads stay fast and liveness is unaffected
        started = time.monotonic()
        for path in ("/health/live", "/api/v1/matches/upcoming", "/api/v1/competitions", "/api/v1/search?q=arsenal"):
            resp = await client.get(path)
            assert resp.status_code == 200, path
        assert time.monotonic() - started < 3.0
        ready = await client.get("/health/ready")
        assert ready.status_code == 503 and ready.json()["dependencies"]["redis"] == "unavailable"
    await wedged.aclose()


# -- the metrics sink ---------------------------------------------------------------------------------------------------------


class RecordingPipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def hincrby(self, key, name, amount):
        self.ops.append((key, name, amount))

    def hset(self, key, mapping):
        self.ops.append(("hset", key, dict(mapping)))

    def expire(self, key, ttl):
        pass

    def execute(self):
        if self.client.fail:
            raise redis_exceptions.ConnectionError("down")
        self.client.pushed.extend(self.ops)


class RecordingClient:
    def __init__(self):
        self.fail = False
        self.pushed = []
        self.pipelines = 0

    def pipeline(self):
        self.pipelines += 1
        return RecordingPipeline(self)


def test_an_api_sink_never_touches_redis_from_add_it_only_flushes_when_told():
    client = RecordingClient()
    sink = RedisMetricsSink("api", client, inline=False)
    for _ in range(1000):
        sink.add("http_requests_total")
        sink.set_gauge("websocket_connections", 3)
    assert client.pipelines == 0  # nothing on the (event-loop) caller's thread
    sink.flush()
    assert client.pipelines == 1
    assert ("football:metrics:counters:api", "http_requests_total", 1000) in client.pushed


def test_an_inline_sink_flushes_at_most_once_a_second():
    clock = Clock()
    client = RecordingClient()
    sink = RedisMetricsSink("worker", client, now=clock, inline=True)
    sink.add("a")
    first = client.pipelines
    for _ in range(100):
        sink.add("a")
    assert client.pipelines == first
    clock.now += 1.5
    sink.add("a")
    assert client.pipelines == first + 1


def test_counts_survive_a_failed_flush_and_are_not_double_counted():
    client = RecordingClient()
    sink = RedisMetricsSink("api", client, inline=False)
    sink.add("x", 5)
    client.fail = True
    sink.flush()  # must not raise
    sink.add("x", 2)
    client.fail = False
    sink.flush()
    assert [op for op in client.pushed if op[1] == "x"] == [("football:metrics:counters:api", "x", 7)]
    sink.flush()
    assert [op for op in client.pushed if op[1] == "x"] == [("football:metrics:counters:api", "x", 7)]  # nothing re-sent


def test_adding_while_another_thread_flushes_loses_nothing():
    client = RecordingClient()
    sink = RedisMetricsSink("api", client, inline=False)
    stop = threading.Event()

    def flusher():
        while not stop.is_set():
            sink.flush()

    thread = threading.Thread(target=flusher)
    thread.start()
    for _ in range(20000):
        sink.add("n")
    stop.set()
    thread.join()
    sink.flush()
    assert sum(op[2] for op in client.pushed if op[1] == "n") == 20000
