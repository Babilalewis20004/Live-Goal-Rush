"""RedisService against fakeredis -- hit/miss/expiry/pub-sub/health_check,
without requiring a real Redis server for the test suite."""

import asyncio


async def test_set_then_get_round_trips_json(fake_redis):
    await fake_redis.set("football:test:key", {"a": 1, "b": [1, 2, 3]})
    assert await fake_redis.get("football:test:key") == {"a": 1, "b": [1, 2, 3]}


async def test_get_missing_key_returns_none(fake_redis):
    assert await fake_redis.get("football:does-not-exist") is None


async def test_delete_removes_key(fake_redis):
    await fake_redis.set("football:test:key", {"a": 1})
    await fake_redis.delete("football:test:key")
    assert await fake_redis.get("football:test:key") is None


async def test_expire_sets_a_ttl(fake_redis):
    await fake_redis.set("football:test:key", "value")
    await fake_redis.expire("football:test:key", 1)
    await asyncio.sleep(1.2)
    assert await fake_redis.get("football:test:key") is None


async def test_set_with_ttl_expires(fake_redis):
    await fake_redis.set("football:test:key", "value", ttl_seconds=1)
    assert await fake_redis.get("football:test:key") == "value"
    await asyncio.sleep(1.2)
    assert await fake_redis.get("football:test:key") is None


async def test_health_check_reports_true_when_reachable(fake_redis):
    assert await fake_redis.health_check() is True


async def test_publish_subscribe_round_trip(fake_redis):
    received = []

    async def _listener():
        async for message in fake_redis.subscribe("football:test:channel"):
            received.append(message)
            break

    listener_task = asyncio.create_task(_listener())
    await asyncio.sleep(0.2)  # let the subscription establish
    await fake_redis.publish("football:test:channel", {"type": "GOAL", "match_id": "1"})
    await asyncio.wait_for(listener_task, timeout=2)

    assert received == [{"type": "GOAL", "match_id": "1"}]
