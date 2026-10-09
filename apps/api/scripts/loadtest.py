"""Scenario load tests against a running stack (Phase 7 §28).

    python scripts/loadtest.py --base http://localhost:8000 --scenario all --scale 1 --out results.json

Dependencies are the ones the API already has (httpx, websockets, asyncpg); no extra load-testing tool is
needed at this scale. Every request goes through the real HTTP stack, so numbers include middleware, the
database, Redis and (with `--base` pointing at the reverse proxy) nginx.

Scenarios (see docs/operations/load-testing.md for what each models):
  home        many visitors opening the home page            (the 4 calls the Next.js home page makes)
  live        many users on live matches                     (live list + a match's detail, events, stats, lineups)
  websocket   many concurrent WebSocket connections          (connect, heartbeat, hold, count drops)
  search      heavy search traffic                           (queries + suggestions)
  spike       match-day traffic spike                        (ramp from idle to peak across a mixed read mix)
  community   community activity during a major match        (comments, reactions, poll votes by many users)
  notify      simultaneous notification generation           (one goal fanned out to every follower, in process)

Authenticated scenarios mint access tokens for the seeded `load*@example.test` users (scripts/seed_volume.py)
using JWT_SECRET, so they bypass the registration rate limit but exercise the real auth dependency.

Results: requests/sec, p50/p95/p99 latency, error rate per scenario, plus resource samples taken during the
run (docker container CPU/memory, Postgres connections, Redis memory/clients/ops, Celery queue depth).
The numbers describe THIS machine and THIS data volume. They are a regression check and a way to find the
first bottleneck, not a capacity promise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


@dataclass
class Result:
    name: str
    requests: int = 0
    errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)

    def record(self, ms: float, status: int | str) -> None:
        self.requests += 1
        self.latencies_ms.append(ms)
        key = str(status)
        self.statuses[key] = self.statuses.get(key, 0) + 1
        # 429 is the rate limiter doing its job under a synthetic single-IP load, not a server failure.
        if isinstance(status, str) or status >= 500:
            self.errors += 1

    def summary(self) -> dict:
        return {
            "scenario": self.name,
            "requests": self.requests,
            "seconds": round(self.seconds, 1),
            "rps": round(self.requests / self.seconds, 1) if self.seconds else 0,
            "p50_ms": round(statistics.median(self.latencies_ms), 1) if self.latencies_ms else 0,
            "p95_ms": round(pct(self.latencies_ms, 95), 1),
            "p99_ms": round(pct(self.latencies_ms, 99), 1),
            "max_ms": round(max(self.latencies_ms), 1) if self.latencies_ms else 0,
            "server_errors": self.errors,
            "error_rate_pct": round(100 * self.errors / self.requests, 3) if self.requests else 0,
            "statuses": dict(sorted(self.statuses.items())),
            **self.extra,
        }


# -- resource sampling -------------------------------------------------------------------------------------------


class Sampler:
    """Polls the things that become the bottleneck, once a second, while a scenario runs."""

    def __init__(self, args) -> None:
        self.args = args
        self.rows: list[dict] = []
        self._task: asyncio.Task | None = None

    async def _docker(self) -> dict:
        if not self.args.docker:
            return {}
        try:
            out = await asyncio.to_thread(
                subprocess.run,
                ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"],
                capture_output=True, text=True, timeout=20,
            )
            stats = {}
            for line in out.stdout.splitlines():
                name, cpu, mem = line.split("|")
                short = name.replace("live-goal-", "").rsplit("-", 1)[0]
                stats[short] = {"cpu": float(cpu.strip("%")), "mem_mb": _mem_mb(mem.split("/")[0])}
            return stats
        except Exception:
            return {}

    async def _pg(self, conn) -> dict:
        if conn is None:
            return {}
        try:
            row = await conn.fetchrow(
                "select count(*) filter (where state='active') as active, count(*) as total from pg_stat_activity where datname = current_database()"
            )
            return {"pg_active": row["active"], "pg_connections": row["total"]}
        except Exception:
            return {}

    async def _redis(self, client) -> dict:
        if client is None:
            return {}
        try:
            info = await client.info()
            return {
                "redis_mem_mb": round(info["used_memory"] / 1048576, 1),
                "redis_clients": info["connected_clients"],
                "redis_ops": info.get("instantaneous_ops_per_sec", 0),
                "queue_depth": await client.llen("football"),
            }
        except Exception:
            return {}

    async def run(self) -> None:
        import asyncpg
        import redis.asyncio as aioredis

        conn = await asyncpg.connect(self.args.pg_dsn) if self.args.pg_dsn else None
        client = aioredis.from_url(self.args.redis_url) if self.args.redis_url else None
        try:
            while True:
                started = time.perf_counter()
                row = {"t": round(time.time(), 1), **await self._pg(conn), **await self._redis(client)}
                docker = await self._docker()
                if docker:
                    row["docker"] = docker
                self.rows.append(row)
                await asyncio.sleep(max(0.0, 1.0 - (time.perf_counter() - started)))
        finally:
            if conn:
                await conn.close()
            if client:
                await client.aclose()

    def start(self) -> None:
        self.rows = []
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> dict:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        return self.summary()

    def summary(self) -> dict:
        out: dict = {}
        if not self.rows:
            return out
        for key in ("pg_active", "pg_connections", "redis_mem_mb", "redis_clients", "redis_ops", "queue_depth"):
            values = [r[key] for r in self.rows if key in r]
            if values:
                out[key] = {"max": max(values), "avg": round(statistics.mean(values), 1)}
        containers: dict[str, dict[str, list[float]]] = {}
        for r in self.rows:
            for name, s in r.get("docker", {}).items():
                containers.setdefault(name, {"cpu": [], "mem_mb": []})
                containers[name]["cpu"].append(s["cpu"])
                containers[name]["mem_mb"].append(s["mem_mb"])
        if containers:
            out["containers"] = {
                n: {"cpu_avg": round(statistics.mean(v["cpu"]), 1), "cpu_max": round(max(v["cpu"]), 1), "mem_max_mb": round(max(v["mem_mb"]), 1)}
                for n, v in containers.items()
            }
        return out


def _mem_mb(text: str) -> float:
    text = text.strip()
    for unit, factor in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024), ("B", 1 / 1048576)):
        if text.endswith(unit):
            return float(text[: -len(unit)]) * factor
    return 0.0


# -- fixtures discovered from the target ------------------------------------------------------------------------------


@dataclass
class World:
    match_ids: list[int] = field(default_factory=list)
    finished_ids: list[int] = field(default_factory=list)
    team_ids: list[int] = field(default_factory=list)
    player_ids: list[int] = field(default_factory=list)
    competition_ids: list[int] = field(default_factory=list)
    slugs: list[str] = field(default_factory=list)
    team_names: list[str] = field(default_factory=list)
    poll_ids: list[int] = field(default_factory=list)
    article_ids: list[int] = field(default_factory=list)
    user_tokens: list[str] = field(default_factory=list)


async def discover(client: httpx.AsyncClient, api: str, args) -> World:
    w = World()
    for path in ("matches/today", "matches/upcoming", "matches/live"):
        r = await client.get(f"{api}/{path}")
        if r.status_code == 200:
            w.match_ids += [m["id"] for m in r.json()]
    listing = await client.get(f"{api}/competitions")
    competitions = listing.json().get("items", []) if listing.status_code == 200 else []
    for comp in competitions:
        w.competition_ids.append(comp["id"])
        st = await client.get(f"{api}/competitions/{comp['id']}/standings")
        if st.status_code == 200 and isinstance(st.json(), list):
            for row in st.json():
                team = row.get("team") or {}
                if team.get("id"):
                    w.team_ids.append(team["id"])
                    if team.get("name"):
                        w.team_names.append(team["name"])
    if args.pg_dsn:  # richer ids straight from the database when we can reach it
        import asyncpg

        conn = await asyncpg.connect(args.pg_dsn)
        try:
            w.match_ids = [r[0] for r in await conn.fetch("select id from matches order by random() limit 200")] or w.match_ids
            w.finished_ids = [r[0] for r in await conn.fetch("select id from matches where status='FINISHED' order by random() limit 100")]
            w.team_ids = [r[0] for r in await conn.fetch("select id from teams order by random() limit 100")] or w.team_ids
            w.team_names = [r[0] for r in await conn.fetch("select name from teams order by random() limit 100")] or w.team_names
            w.player_ids = [r[0] for r in await conn.fetch("select id from players order by random() limit 100")]
            w.slugs = [r[0] for r in await conn.fetch("select slug from articles where status='PUBLISHED' order by random() limit 100")]
            w.article_ids = [r[0] for r in await conn.fetch("select id from articles where status='PUBLISHED' order by random() limit 100")]
            w.poll_ids = [r[0] for r in await conn.fetch("select id from polls where status='OPEN' order by random() limit 50")]
            user_ids = [r[0] for r in await conn.fetch("select id from users where email like 'load%' order by random() limit $1", args.users)]
        finally:
            await conn.close()
        if user_ids:
            from app.core.security import create_access_token

            w.user_tokens = [create_access_token(uid) for uid in user_ids]
    return w


# -- driver -----------------------------------------------------------------------------------------------------------------


async def hammer(client: httpx.AsyncClient, result: Result, make_request, *, duration: float, concurrency: int, ramp: float = 0.0) -> None:
    """`concurrency` workers each issuing requests back to back for `duration` seconds (open-loop-ish: a worker
    sends its next request as soon as the last finishes, which is how a saturating burst of visitors behaves)."""
    stop = time.perf_counter() + duration

    async def worker(index: int) -> None:
        if ramp:
            await asyncio.sleep(ramp * index / concurrency)
        while time.perf_counter() < stop:
            method, url, kwargs = make_request()
            started = time.perf_counter()
            try:
                response = await client.request(method, url, **kwargs)
                status: int | str = response.status_code
            except httpx.HTTPError as exc:
                status = type(exc).__name__
            result.record((time.perf_counter() - started) * 1000, status)

    started = time.perf_counter()
    await asyncio.gather(*[worker(i) for i in range(concurrency)])
    result.seconds = time.perf_counter() - started


async def scenario_home(client, api, w: World, args) -> Result:
    result = Result("home: visitors open the home page")
    # The Next.js home page makes these four calls per visit; one "request" here is one of them.
    calls = [("GET", f"{api}/matches/live"), ("GET", f"{api}/matches/today"), ("GET", f"{api}/matches/upcoming"), ("GET", f"{api}/discovery/home")]
    await hammer(client, result, lambda: (*random.choice(calls), {}), duration=args.duration, concurrency=args.concurrency)
    return result


async def scenario_live(client, api, w: World, args) -> Result:
    result = Result("live: users follow live matches")
    ids = w.match_ids or [1]

    def pick():
        match_id = random.choice(ids)
        path = random.choice(["", "", "/events", "/statistics", "/lineups", "/form", "/head-to-head", "/insights"])
        return ("GET", f"{api}/matches/{match_id}{path}", {})

    await hammer(client, result, lambda: random.choice([pick, pick, lambda: ("GET", f"{api}/matches/live", {})])(), duration=args.duration, concurrency=args.concurrency)
    return result


async def scenario_search(client, api, w: World, args) -> Result:
    result = Result("search: heavy search traffic")
    words = (w.team_names or ["arsenal", "madrid", "barcelona", "city"]) + ["goal", "transfer", "derby", "league", "cup"]

    def pick():
        word = random.choice(words)
        partial = word[: max(2, len(word) - random.randint(0, 3))]
        endpoint = random.choice(["search", "search/suggestions"])
        return ("GET", f"{api}/{endpoint}", {"params": {"q": partial}, "headers": {"X-Forwarded-For": f"198.51.100.{random.randint(1, 250)}"}})

    await hammer(client, result, pick, duration=args.duration, concurrency=args.concurrency)
    return result


async def scenario_spike(client, api, w: World, args) -> Result:
    result = Result("spike: match-day traffic surge")
    ids = w.match_ids or [1]
    mix = [
        lambda: ("GET", f"{api}/matches/live", {}),
        lambda: ("GET", f"{api}/matches/today", {}),
        lambda: ("GET", f"{api}/matches/{random.choice(ids)}", {}),
        lambda: ("GET", f"{api}/matches/{random.choice(ids)}/events", {}),
        lambda: ("GET", f"{api}/discovery/home", {}),
        lambda: ("GET", f"{api}/teams/{random.choice(w.team_ids or [1])}", {}),
        lambda: ("GET", f"{api}/articles/{random.choice(w.slugs)}", {}) if w.slugs else ("GET", f"{api}/articles", {}),
        lambda: ("GET", f"{api}/comments", {"params": {"target_type": "match", "target_id": random.choice(ids)}}),
        lambda: ("GET", f"{api}/competitions/{random.choice(w.competition_ids or [1])}/standings", {}),
    ]
    # idle -> peak over the first third of the run, then hold at peak
    await hammer(client, result, lambda: random.choice(mix)(), duration=args.duration, concurrency=args.concurrency * 4, ramp=args.duration / 3)
    return result


async def scenario_community(client, api, w: World, args) -> Result:
    result = Result("community: comments, reactions and votes during a big match")
    if not w.user_tokens:
        result.extra["skipped"] = "no seeded users (pass --pg-dsn and run scripts/seed_volume.py)"
        return result
    ids = w.match_ids or [1]
    counter = {"n": 0}

    def pick():
        token = random.choice(w.user_tokens)
        headers = {"Authorization": f"Bearer {token}"}
        roll = random.random()
        if roll < 0.35:
            return ("GET", f"{api}/comments", {"params": {"target_type": "match", "target_id": random.choice(ids)}, "headers": headers})
        if roll < 0.60:
            counter["n"] += 1
            return ("POST", f"{api}/comments", {"json": {"target_type": "match", "target_id": random.choice(ids), "body": f"What a game! #{counter['n']}-{random.random()}"}, "headers": headers})
        if roll < 0.85:
            kind = random.choice(["thumbs_up", "fire", "wow", "goal", "heart", "laugh", "clap"])
            return ("PUT", f"{api}/reactions/article/{random.choice(w.article_ids or [1])}", {"json": {"kind": kind}, "headers": headers})
        if w.poll_ids:
            return ("GET", f"{api}/polls/{random.choice(w.poll_ids)}", {"headers": headers})
        return ("GET", f"{api}/feed", {"headers": headers})

    await hammer(client, result, pick, duration=args.duration, concurrency=args.concurrency)
    return result


async def scenario_websocket(client, api, w: World, args) -> Result:
    import websockets

    result = Result(f"websocket: {args.sockets} concurrent connections")
    ws_base = args.base.replace("http", "ws", 1) + "/ws"
    connect_ms: list[float] = []
    pong_ms: list[float] = []
    state = {"connected": 0, "refused": 0, "dropped": 0, "messages": 0}
    ids = w.match_ids or [1]

    async def one(index: int) -> None:
        path = "/matches" if index % 2 == 0 else f"/matches/{random.choice(ids)}"
        started = time.perf_counter()
        try:
            async with websockets.connect(ws_base + path, origin=args.origin, open_timeout=15, max_queue=64) as ws:
                connect_ms.append((time.perf_counter() - started) * 1000)
                state["connected"] += 1
                end = time.perf_counter() + args.duration
                while time.perf_counter() < end:
                    sent = time.perf_counter()
                    await ws.send(json.dumps({"type": "PING"}))
                    try:
                        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    except asyncio.TimeoutError:
                        state["dropped"] += 1
                        return
                    if message.get("type") == "PONG":
                        pong_ms.append((time.perf_counter() - sent) * 1000)
                    state["messages"] += 1
                    await asyncio.sleep(min(5.0, args.duration / 4) + random.random())
        except Exception as exc:  # refused at capacity, reset, timeout
            if state["connected"] and not connect_ms:
                state["dropped"] += 1
            state["refused"] += 1
            result.statuses[type(exc).__name__] = result.statuses.get(type(exc).__name__, 0) + 1

    started = time.perf_counter()
    batch = 100
    tasks = []
    for i in range(args.sockets):
        tasks.append(asyncio.create_task(one(i)))
        if (i + 1) % batch == 0:
            await asyncio.sleep(0.2)  # a ramp, not a thundering herd on one tick
    await asyncio.gather(*tasks)
    result.seconds = time.perf_counter() - started
    result.requests = state["connected"]
    result.latencies_ms = pong_ms
    result.errors = state["refused"] + state["dropped"]
    result.extra.update(
        connected=state["connected"], refused_or_failed=state["refused"], dropped_mid_run=state["dropped"],
        connect_p50_ms=round(statistics.median(connect_ms), 1) if connect_ms else 0, connect_p95_ms=round(pct(connect_ms, 95), 1),
        heartbeat_roundtrips=len(pong_ms),
    )
    return result


async def scenario_notify(client, api, w: World, args) -> Result:
    """One goal in the match whose team has the most followers: resolve everyone to notify, then hand each their
    payload through the real NotificationService with the network senders replaced by a counter. Measures the
    database work (target resolution, dedup ledger, device lookups) -- not Expo or push-service latency."""
    result = Result("notify: one goal fanned out to every follower")
    if not args.pg_dsn:
        result.extra["skipped"] = "needs --pg-dsn"
        return result
    import asyncpg

    conn = await asyncpg.connect(args.pg_dsn)
    try:
        row = await conn.fetchrow("select team_id, count(*) followers from favourite_teams group by team_id order by followers desc limit 1")
        match = await conn.fetchrow("select id from matches where home_team_id = $1 or away_team_id = $1 limit 1", row["team_id"]) if row else None
    finally:
        await conn.close()
    if row is None or match is None:
        result.extra["skipped"] = "no followers/matches seeded"
        return result

    from app.db.session import AsyncSessionLocal, engine
    from app.events.schemas import RealtimeEvent, RealtimeEventType
    from app.services.notification_dispatch_service import resolve_targets
    from app.services.notifications.service import NotificationService

    from app.services.notifications.base import DeliveryResult, PushSender

    class Counter(PushSender):
        sent = 0

        async def send(self, device, payload):
            Counter.sent += 1
            return DeliveryResult(success=True)

    event = RealtimeEvent(type=RealtimeEventType.GOAL, match_id=str(match["id"]), data={"event": {"id": f"loadtest-{time.time_ns()}"}})
    async with AsyncSessionLocal() as db:
        statements = {"n": 0}
        from sqlalchemy import event as sa_event

        @sa_event.listens_for(engine.sync_engine, "before_cursor_execute")
        def _count(*_a):  # noqa: ANN002
            statements["n"] += 1

        started = time.perf_counter()
        targets = await resolve_targets(db, event)
        resolved = time.perf_counter() - started
        service = NotificationService(db)
        service._senders = {platform: Counter() for platform in service._senders}
        batch = getattr(service, "send_to_users", None)
        started = time.perf_counter()
        if batch is not None:
            await batch(targets)
        else:
            for target in targets:
                await service.send_to_user(target)
        delivered = time.perf_counter() - started
    result.seconds = resolved + delivered
    result.requests = len(targets)
    result.latencies_ms = [result.seconds * 1000]
    result.extra.update(
        followers=row["followers"], notified_users=len(targets), pushes_prepared=Counter.sent,
        resolve_seconds=round(resolved, 2), delivery_seconds=round(delivered, 2), total_seconds=round(result.seconds, 2),
        sql_statements=statements["n"], statements_per_user=round(statements["n"] / max(len(targets), 1), 2),
    )
    return result


SCENARIOS = {
    "home": scenario_home, "live": scenario_live, "websocket": scenario_websocket, "search": scenario_search,
    "spike": scenario_spike, "community": scenario_community, "notify": scenario_notify,
}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://localhost:8000", help="API origin (or the reverse proxy)")
    parser.add_argument("--scenario", default="all", help="comma list of: " + ",".join(SCENARIOS) + " | all")
    parser.add_argument("--duration", type=float, default=30, help="seconds per scenario")
    parser.add_argument("--concurrency", type=int, default=50, help="concurrent virtual users")
    parser.add_argument("--sockets", type=int, default=1000, help="WebSocket connections for the websocket scenario")
    parser.add_argument("--users", type=int, default=500, help="seeded users to authenticate as")
    parser.add_argument("--origin", default="http://localhost:3000", help="Origin header for WebSockets (must be in CORS_ORIGINS)")
    parser.add_argument("--pg-dsn", default="", help="postgres://... for ids, connection sampling and the notify scenario")
    parser.add_argument("--redis-url", default="", help="redis://... for memory/clients/queue sampling")
    parser.add_argument("--docker", action="store_true", help="sample `docker stats` for CPU/memory per container")
    parser.add_argument("--out", default="", help="write the full results as JSON")
    args = parser.parse_args()
    if args.pg_dsn:
        # Must happen before anything imports `app.*`: the in-process scenarios (notify) use the app's own engine,
        # and settings are read once at import. Without this they would silently run against the .env database.
        os.environ["DATABASE_URL"] = args.pg_dsn.replace("postgresql://", "postgresql+asyncpg://")

    api = f"{args.base}/api/v1"
    limits = httpx.Limits(max_connections=max(200, args.concurrency * 5), max_keepalive_connections=max(100, args.concurrency * 2))
    names = list(SCENARIOS) if args.scenario == "all" else args.scenario.split(",")
    report: list[dict] = []
    async with httpx.AsyncClient(timeout=30, limits=limits) as client:
        world = await discover(client, api, args)
        print(f"target {args.base}: {len(world.match_ids)} matches, {len(world.team_ids)} teams, {len(world.slugs)} articles, {len(world.user_tokens)} users", flush=True)
        for name in names:
            sampler = Sampler(args)
            sampler.start()
            result = await SCENARIOS[name](client, api, world, args)
            resources = await sampler.stop()
            summary = {**result.summary(), "resources": resources}
            report.append(summary)
            print(json.dumps({k: v for k, v in summary.items() if k != "resources"}), flush=True)
            if resources:
                print("   resources:", json.dumps(resources), flush=True)
            await asyncio.sleep(2)
    if args.out:
        with open(args.out, "w", encoding="utf8") as handle:
            json.dump({"base": args.base, "args": vars(args), "results": report}, handle, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
