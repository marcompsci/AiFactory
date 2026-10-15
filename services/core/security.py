"""HTTP hardening shared by every route (see SECURITY.md, "Backend hardening").

* Security headers on every response: no sniffing, no framing, no referrer, locked-down permissions, a deny-all CSP
  for JSON (routes that serve files set their own), `no-store` caching for the API, HSTS behind HTTPS.
* Request bodies are capped (AICIV_MAX_BODY_BYTES, default 1 MB; uploads 20 MB), including chunked bodies.
* A per-client request budget on the whole API (AICIV_REQUESTS_PER_MINUTE, default 600), on top of the per-user
  mutation limiter.
* Failed credentials are throttled per client address: after AICIV_AUTH_FAILURES (default 10) bad tokens in 5 minutes,
  that address gets 429 for 15 minutes. Step-up codes have their own per-user lockout.
* Every response carries an X-Request-ID; unexpected errors return a generic message with that id (details only in
  the server log), never a stack trace.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("aiciv.security")

UPLOAD_PATHS = ("/upload", "/tax/documents")


def _client(scope: Scope) -> str:
    c = scope.get("client")
    return c[0] if c else "unknown"


class FailureLimiter:
    """Counts failures per key in a sliding window; locks the key out once the limit is reached."""

    def __init__(self, limit: int, window_s: float, lockout_s: float) -> None:
        self.limit, self.window, self.lockout = limit, window_s, lockout_s
        self._fails: dict[str, list[float]] = {}
        self._locked: dict[str, float] = {}
        self._lock = threading.Lock()

    def locked(self, key: str) -> float:
        """Seconds left in the lockout (0 if not locked)."""
        with self._lock:
            until = self._locked.get(key, 0)
            left = until - time.monotonic()
            if left <= 0 and key in self._locked:
                del self._locked[key]
            return max(0.0, left)

    def fail(self, key: str) -> bool:
        """Records a failure; True if this failure triggered a lockout."""
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._fails.get(key, []) if now - t < self.window] + [now]
            self._fails[key] = hits
            if len(hits) >= self.limit:
                self._locked[key] = now + self.lockout
                self._fails[key] = []
                return True
            return False

    def succeed(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._fails.clear()
            self._locked.clear()


auth_failures = FailureLimiter(int(os.environ.get("AICIV_AUTH_FAILURES", "10")), 300, 900)
stepup_failures = FailureLimiter(5, 600, 900)


class _Window:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            start, n = self._hits.get(key, (now, 0))
            if now - start >= 60:
                start, n = now, 0
            n += 1
            self._hits[key] = (start, n)
            return n <= self.per_minute

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


request_budget = _Window(int(os.environ.get("AICIV_REQUESTS_PER_MINUTE", "600")))


class HardeningMiddleware:
    """Pure ASGI (so it never buffers the SSE stream)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.max_body = int(os.environ.get("AICIV_MAX_BODY_BYTES", str(1_000_000)))
        self.max_upload = int(os.environ.get("AICIV_MAX_UPLOAD_BYTES", str(20_000_000)))
        self.hsts = os.environ.get("AICIV_HSTS", "auto")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path: str = scope.get("path", "")
        rid = uuid.uuid4().hex[:16]
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        https = scope.get("scheme") == "https" or headers.get("x-forwarded-proto") == "https"

        async def respond(status: int, detail: str, extra: list[tuple[bytes, bytes]] | None = None) -> None:
            body = ('{"detail":"%s","request_id":"%s"}' % (detail, rid)).encode()
            await send({"type": "http.response.start", "status": status,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())] + (extra or [])
                        + self._headers(path, https, rid, [])})
            await send({"type": "http.response.body", "body": body})

        if path.startswith("/api/") and scope.get("method") != "OPTIONS":
            if not request_budget.allow(_client(scope)):
                return await respond(429, "too many requests", [(b"retry-after", b"60")])
            left = auth_failures.locked(_client(scope))
            if left:
                return await respond(429, "too many failed sign-in attempts; try again later", [(b"retry-after", str(int(left) + 1).encode())])

        limit = self.max_upload if any(path.endswith(p) for p in UPLOAD_PATHS) else self.max_body
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            return await respond(413, "request body too large")

        received = 0
        too_large = False

        async def capped_receive() -> Message:
            nonlocal received, too_large
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > limit:
                    # stop reading; whatever the app answers is replaced by a 413 below
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return msg

        started = False
        swallow = False

        async def secured_send(msg: Message) -> None:
            nonlocal started, swallow
            if swallow:
                return
            if msg["type"] == "http.response.start":
                started = True
                if too_large:
                    swallow = True
                    return await respond(413, "request body too large")
                msg = dict(msg)
                msg["headers"] = list(msg.get("headers", [])) + self._headers(path, https, rid, msg.get("headers", []))
            await send(msg)

        try:
            await self.app(scope, capped_receive, secured_send)
        except _TooLarge:
            if not started:
                await respond(413, "request body too large")
        except Exception:  # noqa: BLE001 — never leak internals; the id ties the client's report to the log line
            log.exception("unhandled error request_id=%s path=%s", rid, path)
            if not started:
                await respond(500, "internal error")

    def _headers(self, path: str, https: bool, rid: str, existing) -> list[tuple[bytes, bytes]]:
        have = {k.decode().lower() if isinstance(k, bytes) else k.lower() for k, _ in existing}
        out = [(b"x-request-id", rid.encode()), (b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
               (b"referrer-policy", b"no-referrer"), (b"cross-origin-opener-policy", b"same-origin"),
               (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()")]
        if "content-security-policy" not in have:
            out.append((b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"))
        if path.startswith("/api/") and "cache-control" not in have:
            out.append((b"cache-control", b"no-store"))
        if (self.hsts == "1") or (self.hsts == "auto" and https):
            out.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
        return out


class _TooLarge(Exception):
    pass
