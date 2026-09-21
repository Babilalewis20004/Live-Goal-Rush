"""CacheAside: hit/miss against a Pydantic model, and graceful fallback to
the loader (not a crash) when Redis itself is unreachable."""

from pydantic import BaseModel

from app.core.redis_client import RedisService
from app.services.cache import CacheAside


class _Widget(BaseModel):
    id: int
    name: str


class _AlwaysBrokenRedis(RedisService):
    """Simulates a Redis outage: every operation raises, the way a real
    connection failure would."""

    def __init__(self) -> None:  # no super().__init__ -- never touches a real client
        pass

    async def get(self, key: str):
        raise ConnectionError("redis is down")

    async def set(self, key: str, value, *, ttl_seconds=None) -> None:
        raise ConnectionError("redis is down")

    async def delete(self, *keys: str) -> None:
        raise ConnectionError("redis is down")


async def test_cache_miss_calls_loader_and_populates_cache(fake_redis):
    cache = CacheAside(fake_redis)
    calls = 0

    async def loader() -> _Widget:
        nonlocal calls
        calls += 1
        return _Widget(id=1, name="ball")

    result = await cache.get_or_set_model("widget:1", _Widget, loader, ttl_seconds=60)
    assert result == _Widget(id=1, name="ball")
    assert calls == 1


async def test_cache_hit_does_not_call_loader(fake_redis):
    cache = CacheAside(fake_redis)
    await fake_redis.set("widget:1", {"id": 1, "name": "ball"})
    calls = 0

    async def loader() -> _Widget:
        nonlocal calls
        calls += 1
        return _Widget(id=99, name="should-not-be-returned")

    result = await cache.get_or_set_model("widget:1", _Widget, loader, ttl_seconds=60)
    assert result == _Widget(id=1, name="ball")
    assert calls == 0


async def test_list_cache_hit_and_miss(fake_redis):
    cache = CacheAside(fake_redis)

    async def loader() -> list[_Widget]:
        return [_Widget(id=1, name="a"), _Widget(id=2, name="b")]

    first = await cache.get_or_set_list("widgets", _Widget, loader, ttl_seconds=60)
    assert first == [_Widget(id=1, name="a"), _Widget(id=2, name="b")]

    async def loader_should_not_run() -> list[_Widget]:
        raise AssertionError("loader should not run on a cache hit")

    second = await cache.get_or_set_list("widgets", _Widget, loader_should_not_run, ttl_seconds=60)
    assert second == first


async def test_redis_outage_falls_back_to_loader_instead_of_raising():
    cache = CacheAside(_AlwaysBrokenRedis())

    async def loader() -> _Widget:
        return _Widget(id=1, name="ball")

    result = await cache.get_or_set_model("widget:1", _Widget, loader, ttl_seconds=60)
    assert result == _Widget(id=1, name="ball")


async def test_invalidate_does_not_raise_when_redis_is_down():
    cache = CacheAside(_AlwaysBrokenRedis())
    await cache.invalidate("widget:1")  # must not raise
