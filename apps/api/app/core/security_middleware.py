"""Baseline HTTP hardening: response security headers and request body size limits.

Pure ASGI middleware (no ``BaseHTTPMiddleware``) so the body limit can wrap the receive
channel and stop reading an oversized stream rather than buffering it.
"""

from __future__ import annotations

import json

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.problem_details import PROBLEM_CONTENT_TYPE

# The interactive docs load assets and scripts from a CDN, so they get no restrictive CSP
# (docs are disabled in production).
_DOC_PREFIXES = ("/docs", "/redoc", "/openapi.json")
_API_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware:
    """Adds conservative security headers to every response."""

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self._hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        is_doc = path.startswith(_DOC_PREFIXES)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                extra = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"no-referrer",
                    b"cross-origin-resource-policy": b"same-site",
                }
                if not is_doc:
                    extra[b"content-security-policy"] = _API_CSP.encode()
                    # API responses carry per-user data: never let shared caches keep them.
                    # Tile responses set their own validators/caching explicitly.
                    if b"cache-control" not in present:
                        extra[b"cache-control"] = b"no-store"
                if self._hsts:
                    extra[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                merged = [(k, v) for k, v in message.get("headers", []) if k.lower() not in extra]
                merged.extend(extra.items())
                message = {**message, "headers": merged}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than ``max_bytes`` with 413 (problem+json)."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self._max:
            await self._reject(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max:
                    # Raised inside the application so it renders as a normal problem response.
                    raise HTTPException(status_code=413, detail="The request body is too large.")
            return message

        await self.app(scope, limited_receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        body = json.dumps(
            {
                "type": "about:blank",
                "title": "Payload Too Large",
                "status": 413,
                "detail": f"The request body exceeds the {self._max}-byte limit.",
                "instance": scope["path"],
                "code": "payload_too_large",
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", PROBLEM_CONTENT_TYPE.encode()),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
