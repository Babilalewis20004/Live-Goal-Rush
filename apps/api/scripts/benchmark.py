"""Latency benchmark for the Phase 6 hot endpoints against a running stack.

    python scripts/benchmark.py --base http://localhost:8000 --requests 200 --concurrency 10

Measures, per endpoint, cold (first request, a cache miss) and warm (the rest) latency percentiles with
`N` requests at the given concurrency, then prints the API's cache hit ratio and the Celery queue length from
`/metrics`. It only reads public endpoints (analytics, comparison, prediction, comments, polls, search) and
creates nothing. Results depend on the machine and the data volume -- they are a regression check, not a capacity claim.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


async def timed(client: httpx.AsyncClient, url: str) -> tuple[float, int]:
    start = time.perf_counter()
    response = await client.get(url)
    return (time.perf_counter() - start) * 1000, response.status_code


async def bench(client: httpx.AsyncClient, name: str, url: str, requests: int, concurrency: int) -> None:
    cold, status = await timed(client, url)
    sem = asyncio.Semaphore(concurrency)
    samples: list[float] = []
    statuses: dict[int, int] = {}

    async def one() -> None:
        async with sem:
            ms, code = await timed(client, url)
            samples.append(ms)
            statuses[code] = statuses.get(code, 0) + 1

    started = time.perf_counter()
    await asyncio.gather(*[one() for _ in range(requests)])
    elapsed = time.perf_counter() - started
    print(
        f"{name:<34} cold {cold:7.1f} ms | warm p50 {statistics.median(samples):6.1f}  p95 {pct(samples, 95):6.1f}  "
        f"p99 {pct(samples, 99):6.1f} ms | {requests / elapsed:6.0f} req/s | status {statuses} (first: {status})"
    )


def metric(text: str, name: str) -> float:
    total = 0.0
    for line in text.splitlines():
        if line.startswith(name) and not line.startswith("#"):
            total += float(line.rsplit(" ", 1)[1])
    return total


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    api = f"{args.base}/api/v1"

    async with httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=args.concurrency * 2)) as c:
        matches = (await c.get(f"{api}/matches/today")).json() + (await c.get(f"{api}/matches/upcoming")).json()
        if not matches:
            raise SystemExit("No matches in the database; start the stack and let the first provider sync finish.")
        match = matches[0]
        team_id = match["home_team"]["id"]
        before = (await c.get(f"{args.base}/metrics")).text
        targets = [
            ("team analytics (basic)", f"{api}/teams/{team_id}/analytics"),
            ("match comparison (basic)", f"{api}/matches/{match['id']}/comparison"),
            ("match prediction", f"{api}/matches/{match['id']}/prediction"),
            ("match insights (computed)", f"{api}/matches/{match['id']}/insights"),
            ("match insight records", f"{api}/matches/{match['id']}/insight-records"),
            ("head-to-head", f"{api}/matches/{match['id']}/head-to-head"),
            ("comments (match)", f"{api}/comments?target_type=match&target_id={match['id']}"),
            ("reactions (match)", f"{api}/reactions/match/{match['id']}"),
            ("polls (match)", f"{api}/polls?match_id={match['id']}"),
            ("discovery home", f"{api}/discovery/home"),
            ("search", f"{api}/search?q=ars"),
            ("live matches", f"{api}/matches/live"),
        ]
        for name, url in targets:
            await bench(c, name, url, args.requests, args.concurrency)
        after = (await c.get(f"{args.base}/metrics")).text

    hits = metric(after, "cache_hits_total") - metric(before, "cache_hits_total")
    misses = metric(after, "cache_misses_total") - metric(before, "cache_misses_total")
    if hits + misses:
        print(f"\nRedis cache during the run: {hits:.0f} hits / {misses:.0f} misses = {hits / (hits + misses):.1%} hit rate")
    print(f"Celery queue length now: {metric(after, 'celery_queue_length'):.0f}")


if __name__ == "__main__":
    asyncio.run(main())
