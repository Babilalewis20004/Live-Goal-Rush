"""HTTP-level protections that apply to every response and request (Phase 7).

Pure ASGI middleware (not `BaseHTTPMiddleware`), so they add no per-request task or streaming overhead.

* `SecurityHeadersMiddleware` -- the API serves JSON and images, never HTML pages, so its CSP can be
  maximally strict; the web app sets its own (nonce-based) CSP in `apps/web/proxy.ts`.
* `BodyLimitMiddleware` -- refuses an oversized request body with 413 before a handler buffers it. A declared
  `Content-Length` is rejected up front; a chunked body is counted as it streams. The reverse proxy enforces
  the same ceiling first (`deploy/nginx/nginx.conf`); this is the backstop when the API is reached directly.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from app.core.config import settings

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_STATIC_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
]
_HSTS = (b"strict-transport-security", b"max-age=63072000; includeSubDomains")
# Responses that carry or set credentials must never be stored by a shared cache.
_NO_STORE_PREFIXES = ("/api/v1/auth", "/api/v1/users/me", "/api/v1/me", "/api/v1/subscription", "/api/v1/admin", "/api/v1/profiles/me")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        no_store = path.startswith(_NO_STORE_PREFIXES)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {name.lower() for name, _ in headers}
                for name, value in _STATIC_HEADERS:
                    if name not in present:
                        headers.append((name, value))
                if self.hsts and _HSTS[0] not in present:
                    headers.append(_HSTS)
                if no_store and b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, send_with_headers)


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, default_limit: int, upload_prefix: str = "/api/v1/editor/media", upload_limit: int = 0) -> None:
        self.app = app
        self.default_limit = default_limit
        self.upload_prefix = upload_prefix
        self.upload_limit = upload_limit or default_limit

    def limit_for(self, scope: Scope) -> int:
        path = scope.get("path", "")
        if scope.get("method") in ("POST", "PUT") and path.startswith(self.upload_prefix):
            return self.upload_limit
        return self.default_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send, status=400)
                return

        received = 0
        started = False
        too_large = False
        answered = False

        async def counting_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    too_large = True
                    raise _TooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started, answered
            if too_large and not started:
                # FastAPI turns an exception raised while reading the body into its own 400 response; whatever the
                # application tried to say, the truthful answer is 413. Replace it, once.
                if not answered:
                    answered = True
                    await self._reject(send)
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started and not answered:
                await self._reject(send)

    @staticmethod
    async def _reject(send: Send, status: int = 413) -> None:
        body = json.dumps({"detail": "Request body too large" if status == 413 else "Invalid Content-Length"}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})


def configure(app) -> None:  # noqa: ANN001 - FastAPI
    """Attach both middleware. Order matters little here: neither depends on the other."""
    app.add_middleware(
        BodyLimitMiddleware,
        default_limit=settings.max_request_body_bytes,
        upload_limit=settings.media_max_bytes + settings.max_request_body_bytes,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_deployed)
