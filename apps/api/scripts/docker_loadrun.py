"""Run the load scenarios from INSIDE the compose network and sample container CPU/memory from the host.

    python scripts/docker_loadrun.py --scenarios home,live,search,spike,community,websocket,notify --out results.json

Why in the network: running the generator on a developer's Windows/macOS host sends every request through Docker
Desktop's port forwarding and competes with the stack for the same CPUs, which understates what the API can do.
The generator is the API image itself (scripts/loadtest.py ships in it), attached to the compose network.

Resource numbers come from `docker stats` on the host, sampled every ~2 s for the duration of each scenario.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time


def sample(stop: threading.Event, rows: list[dict]) -> None:
    while not stop.is_set():
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"],
            capture_output=True, text=True, timeout=30,
        ).stdout
        row = {}
        for line in out.splitlines():
            name, cpu, mem = line.split("|")
            mem_value, _, _ = mem.partition("/")
            factor = 1024 if "GiB" in mem_value else 1
            row[name.replace("live-goal-", "").rsplit("-", 1)[0]] = (float(cpu.strip("%")), float(mem_value.strip().rstrip("MiBGi")) * factor)
        rows.append(row)


def summarize(rows: list[dict]) -> dict:
    names = {n for r in rows for n in r}
    result = {}
    for name in sorted(names):
        cpu = [r[name][0] for r in rows if name in r]
        mem = [r[name][1] for r in rows if name in r]
        if cpu and max(cpu) > 1.0:
            result[name] = {"cpu_avg": round(statistics.mean(cpu), 1), "cpu_max": round(max(cpu), 1), "mem_max_mb": round(max(mem), 1)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", default="home,live,search,spike,community,websocket,notify")
    parser.add_argument("--duration", default="30")
    parser.add_argument("--concurrency", default="50")
    parser.add_argument("--sockets", default="1000")
    parser.add_argument("--db", default="football_perf")
    parser.add_argument("--out", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--generators", type=int, default=1, help="parallel generator containers (one Python process tops out near 30-40 rps of heavy traffic)")
    args = parser.parse_args()

    report = []
    for scenario in args.scenarios.split(","):
        rows: list[dict] = []
        stop = threading.Event()
        thread = threading.Thread(target=sample, args=(stop, rows), daemon=True)
        thread.start()
        started = time.time()
        command = [
            "docker", "compose", "run", "--rm", "--no-deps", "-T", "-e", "LOG_LEVEL=ERROR",
            "api", "python", "scripts/loadtest.py",
            "--base", "http://api:8000", "--scenario", scenario, "--duration", args.duration,
            "--concurrency", args.concurrency, "--sockets", args.sockets, "--users", "500",
            "--origin", "http://localhost:3000",
            "--pg-dsn", f"postgresql://football:football@postgres:5432/{args.db}",
            "--redis-url", "redis://redis:6379/0",
        ]
        procs = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(args.generators)]
        outputs = [p.communicate() for p in procs]
        stop.set()
        thread.join(timeout=35)
        lines = [next((l for l in out.splitlines() if l.startswith('{"scenario"')), None) for out, _ in outputs]
        if not all(lines):
            print(f"[{scenario}] no result", outputs[0][0][-800:], outputs[0][1][-800:], sep="\n", file=sys.stderr)
            continue
        parts = [json.loads(l) for l in lines]
        entry = dict(parts[0])
        if len(parts) > 1:
            total = sum(p["requests"] for p in parts)
            weight = lambda key: round(sum(p[key] * p["requests"] for p in parts) / max(total, 1), 1)  # noqa: E731
            entry.update(
                requests=total,
                rps=round(sum(p["rps"] for p in parts), 1),
                p50_ms=weight("p50_ms"), p95_ms=weight("p95_ms"), p99_ms=weight("p99_ms"),
                max_ms=max(p["max_ms"] for p in parts),
                server_errors=sum(p["server_errors"] for p in parts),
                error_rate_pct=round(100 * sum(p["server_errors"] for p in parts) / max(total, 1), 3),
                generators=len(parts),
            )
            statuses: dict[str, int] = {}
            for p in parts:
                for k, v in p["statuses"].items():
                    statuses[k] = statuses.get(k, 0) + v
            entry["statuses"] = statuses
        entry["containers"] = summarize(rows)
        entry["wall_seconds"] = round(time.time() - started, 1)
        report.append(entry)
        short = {k: entry[k] for k in ("scenario", "requests", "rps", "p50_ms", "p95_ms", "p99_ms", "server_errors", "error_rate_pct", "statuses") if k in entry}
        print(json.dumps(short), flush=True)
        print("   containers:", json.dumps(entry["containers"]), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf8") as handle:
            json.dump({"label": args.label, "results": report}, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
