"""Turn the files load/run-suite.sh wrote into one markdown table.

    python load/summarize.py load/results/1w "1 uvicorn worker"

Reads k6's JSON summary when present, and falls back to the end-of-test text k6 printed into <scenario>.log (k6 skips
nothing in the log even when a threshold is crossed).
"""
from __future__ import annotations

import json
import os
import re
import sys

_UNITS = {"µs": 0.001, "us": 0.001, "ms": 1.0, "s": 1000.0, "m": 60000.0}


def to_ms(text: str) -> float:
    match = re.fullmatch(r"([0-9.]+)(µs|us|ms|s|m)", text.strip())
    return float(match.group(1)) * _UNITS[match.group(2)] if match else 0.0


def from_log(path: str) -> dict:
    """Rebuild the parts of k6's JSON summary this report needs from the text summary."""
    metrics: dict = {}
    if not os.path.exists(path):
        return metrics
    for line in open(path, encoding="utf8", errors="replace"):
        match = re.match(r"\s*([a-z_]+)\.{2,}:\s*(.*)$", line)
        if not match:
            continue
        name, rest = match.groups()
        stats = dict(re.findall(r"([a-z()0-9]+)=([0-9.µa-z]+)", rest))
        if name in ("http_req_duration", "ws_connect_ms") and "med" in stats:
            metrics[name] = {"med": to_ms(stats["med"]), "p(95)": to_ms(stats["p(95)"]), "p(99)": to_ms(stats["p(99)"]), "max": to_ms(stats["max"])}
        elif name in ("http_reqs", "server_errors", "ws_sessions", "ws_dropped"):
            numbers = re.match(r"([0-9]+)\s+([0-9.]+)/s", rest)
            if numbers:
                metrics[name] = {"count": int(numbers.group(1)), "rate": float(numbers.group(2))}
        elif name == "vus_max":
            maximum = re.search(r"max=([0-9]+)", rest)
            if maximum:
                metrics[name] = {"value": int(maximum.group(1))}
    return metrics


def load(path: str) -> dict:
    return json.load(open(path, encoding="utf8")) if os.path.exists(path) else {}


def main() -> None:
    directory, label = sys.argv[1], sys.argv[2]
    print(f"### {label}\n")
    print("| scenario | peak VUs | req/s | p50 | p95 | p99 | max | 5xx / transport errors | api CPU (cores avg) | api RAM peak | worker CPU | postgres CPU | PG conns (active) | Redis MB / clients | queue max |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name in ("home", "live", "search", "spike", "community", "websocket"):
        summary = load(os.path.join(directory, f"{name}.json")).get("metrics") or from_log(os.path.join(directory, f"{name}.log"))
        if not summary:
            continue
        res = load(os.path.join(directory, f"{name}.res.json"))
        cont = res.get("containers", {})
        dur = summary.get("http_req_duration", {})
        reqs = summary.get("http_reqs", {})
        errors = int(summary.get("server_errors", {}).get("count", 0))
        vus = int(summary.get("vus_max", {}).get("value", 0))
        infra = f"{res.get('pg_conns_max', '?')} ({res.get('pg_active_max', '?')}) | {res.get('redis_mb', '?')} / {res.get('redis_clients', '?')} | {res.get('queue_max', '?')}"
        resources = f"{cont.get('api', {}).get('cpu_cores_avg', '?')} | {cont.get('api', {}).get('mem_peak_mb', '?')} MB | {cont.get('worker', {}).get('cpu_cores_avg', '?')} | {cont.get('postgres', {}).get('cpu_cores_avg', '?')}"
        if name == "websocket":
            conn = summary.get("ws_connect_ms", {})
            dropped = int(summary.get("ws_dropped", {}).get("count", 0))
            print(
                f"| websocket (all held open 30 s) | {vus} | - | connect {conn.get('med', 0):.0f} ms | connect {conn.get('p(95)', 0):.0f} ms | connect {conn.get('p(99)', 0):.0f} ms | "
                f"connect {conn.get('max', 0):.0f} ms | {dropped} dropped | {resources} | {infra} |"
            )
            continue
        print(
            f"| {name} | {vus} | {reqs.get('rate', 0):.1f} | {dur.get('med', 0):.0f} ms | {dur.get('p(95)', 0):.0f} ms | {dur.get('p(99)', 0):.0f} ms | {dur.get('max', 0):.0f} ms | "
            f"{errors} ({100 * errors / max(reqs.get('count', 1), 1):.2f}%) | {resources} | {infra} |"
        )
    print()


if __name__ == "__main__":
    main()
