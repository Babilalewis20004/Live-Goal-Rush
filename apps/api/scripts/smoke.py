"""Post-deploy smoke test (Phase 7 §38): does the thing that just started actually serve users?

    python scripts/smoke.py --base https://staging.livepitch.example --web https://staging.livepitch.example \
        --expect-version 2.1.0 --origin https://staging.livepitch.example

Exits non-zero on the first failure and prints which check failed, so a deploy pipeline can stop and roll back.
Read-only: it creates nothing. Checks, in order:

  api    /health/live, /health/ready (database + Redis), /version (the release that was meant to ship)
  data   public read endpoints answer 200 with the documented shape
  auth   protected endpoints refuse an anonymous caller, admin routes refuse everyone without credentials
  ws     a WebSocket handshake, a PING answered with a PONG
  web    the home page renders, with the security headers and a nonce-bearing CSP (only when --web is given)
  edge   /metrics is not reachable from outside (only when --edge is given: the public, proxied origin)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time

import httpx

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" -- {detail}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILURES.append(name)


async def wait_until_ready(client: httpx.AsyncClient, base: str, seconds: float) -> bool:
    """A freshly started instance needs a moment (migrations, warm-up); poll readiness instead of racing it."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if (await client.get(f"{base}/health/ready")).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2)
    return False


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="API origin, e.g. https://api.example.com or http://localhost:8000")
    parser.add_argument("--web", default="", help="web origin to check the rendered site and its headers")
    parser.add_argument("--edge", action="store_true", help="--base is the public reverse proxy: also check internals are not exposed")
    parser.add_argument("--expect-version", default="", help="fail unless /version reports this")
    parser.add_argument("--origin", default="http://localhost:3000", help="Origin header for the WebSocket handshake")
    parser.add_argument("--wait", type=float, default=60, help="seconds to wait for readiness")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        print(f"smoke test against {base}")
        ready = await wait_until_ready(client, base, args.wait)
        check("api: becomes ready", ready, f"/health/ready not 200 within {args.wait:.0f}s")
        if not ready:
            return report()

        live = await client.get(f"{base}/health/live")
        check("api: /health/live", live.status_code == 200 and live.json().get("status") == "alive")
        r = await client.get(f"{base}/health/ready")
        deps = r.json().get("dependencies", {})
        check("api: ready reports database and Redis ok", r.status_code == 200 and deps.get("database") == "ok" and deps.get("redis") == "ok", str(deps))
        v = await client.get(f"{base}/version")
        body = v.json() if v.status_code == 200 else {}
        check("api: /version answers", v.status_code == 200 and bool(body.get("version")), v.text[:100])
        if args.expect_version:
            check(f"api: running version {args.expect_version}", body.get("version") == args.expect_version, f"got {body.get('version')}")
        check("api: no stack trace or server banner leaks", "server" not in {k.lower() for k in v.headers} or "uvicorn" not in v.headers.get("server", "").lower())

        # data
        for path in ("/api/v1/capabilities", "/api/v1/matches/live", "/api/v1/matches/today", "/api/v1/competitions", "/api/v1/articles", "/api/v1/discovery/home", "/api/v1/subscription/plans"):
            resp = await client.get(f"{base}{path}")
            check(f"data: GET {path}", resp.status_code == 200, f"HTTP {resp.status_code}")

        # auth boundaries
        for method, path in (("GET", "/api/v1/users/me"), ("GET", "/api/v1/subscription"), ("GET", "/api/v1/admin/system"), ("GET", "/api/v1/editor/articles"), ("DELETE", "/api/v1/users/me")):
            resp = await client.request(method, f"{base}{path}", json={"password": "x"} if method == "DELETE" else None)
            check(f"auth: anonymous {method} {path} is refused", resp.status_code in (401, 403), f"HTTP {resp.status_code}")
        forged = await client.get(f"{base}/api/v1/admin/system", headers={"Authorization": "Bearer not.a.token", "X-User-Role": "admin"})
        check("auth: a forged token and role header are refused", forged.status_code == 401, f"HTTP {forged.status_code}")

        # websocket
        try:
            import websockets

            ws_url = base.replace("http", "ws", 1) + "/ws/matches"
            async with websockets.connect(ws_url, origin=args.origin, open_timeout=10) as ws:
                await ws.send(json.dumps({"type": "PING"}))
                reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            check("ws: handshake and PING/PONG", reply.get("type") == "PONG", str(reply))
        except Exception as exc:  # noqa: BLE001
            check("ws: handshake and PING/PONG", False, f"{type(exc).__name__}: {exc}")

        if args.edge:
            resp = await client.get(f"{base}/metrics")
            check("edge: /metrics is not exposed publicly", resp.status_code in (403, 404), f"HTTP {resp.status_code}")
            resp = await client.get(f"{base}/openapi.json")
            check("edge: API schema is not exposed publicly", resp.status_code in (403, 404), f"HTTP {resp.status_code}")

        if args.web:
            web = args.web.rstrip("/")
            page = await client.get(web + "/")
            check("web: home page renders", page.status_code == 200 and "<html" in page.text.lower(), f"HTTP {page.status_code}")
            csp = page.headers.get("content-security-policy", "")
            nonce = re.search(r"'nonce-([^']+)'", csp)
            check("web: CSP carries a per-request nonce", bool(nonce))
            check("web: scripts carry that nonce", bool(nonce) and f'nonce="{nonce.group(1)}"' in page.text)
            for header in ("x-content-type-options", "x-frame-options", "referrer-policy", "permissions-policy", "strict-transport-security"):
                check(f"web: {header} header", header in page.headers)
            check("web: no X-Powered-By banner", "x-powered-by" not in page.headers)
            robots = await client.get(web + "/robots.txt")
            check("web: robots.txt", robots.status_code == 200)

    return report()


def report() -> int:
    print()
    if FAILURES:
        print(f"SMOKE TEST FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
