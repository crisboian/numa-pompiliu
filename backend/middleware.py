"""NUMA Capture Web — middleware for security and rate limiting.

Provides:
- Rate limiting (in-memory sliding window per IP)
- Security headers (CSP, HSTS, X-Frame, X-Content-Type, Referrer-Policy)
- Request body size limit
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

# ─── Config from env ────────────────────────────────────────────────────────

RATE_LIMIT_ENABLED = os.environ.get("NUMA_RATE_LIMIT", "true").lower() == "true"
RATE_LIMIT_REQUESTS = int(os.environ.get("NUMA_RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.environ.get("NUMA_RATE_LIMIT_WINDOW", "60"))  # seconds
MAX_BODY_SIZE = int(os.environ.get("NUMA_MAX_BODY_SIZE", "1048576"))  # 1 MB

# ─── CSP (Content Security Policy) ──────────────────────────────────────────

# Restrictive by default; tighten further in production.
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)

# ─── Rate limiter (in-memory sliding window) ────────────────────────────────


class InMemoryRateLimiter:
    """Sliding-window rate limiter per client IP.

    Thread-safe enough for single-process uvicorn with multiple workers.
    For distributed deployments, replace with Redis or similar.
    """

    def __init__(
        self, max_requests: int = 100, window_seconds: int = 60
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def check(self, client_ip: str) -> bool:
        """Return True if request is allowed, False if rate-limited."""
        now = time.monotonic()
        cutoff = now - self._window
        bucket = self._buckets[client_ip]
        # Prune old entries
        self._buckets[client_ip] = [t for t in bucket if t > cutoff]
        bucket = self._buckets[client_ip]
        if len(bucket) >= self._max:
            return False
        bucket.append(now)
        return True

    @property
    def stats(self) -> dict[str, Any]:
        """Return current stats (for /health /admin)."""
        now = time.monotonic()
        cutoff = now - self._window
        active = sum(
            1 for timestamps in self._buckets.values()
            if any(t > cutoff for t in timestamps)
        )
        return {
            "enabled": RATE_LIMIT_ENABLED,
            "max_requests": self._max,
            "window_seconds": self._window,
            "active_clients": active,
        }


rate_limiter = InMemoryRateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW)

# ─── Security headers middleware ────────────────────────────────────────────

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP_POLICY,
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), "
        "interest-cohort=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

PUBLIC_PATHS = {"/health", "/", "/capture", "/capture.html", "/api/phases"}


def setup_middleware(app: FastAPI) -> None:
    """Register all middleware on the FastAPI app.

    Order matters: outermost middleware runs first on request.
    """

    # ── 1. Security headers (outermost — runs first) ───────────────────────
    @app.middleware("http")
    async def security_headers_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response

    # ── 2. Body size limit ─────────────────────────────────────────────────
    @app.middleware("http")
    async def body_size_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_SIZE:
            return JSONResponse(
                status_code=413,
                content={
                    "error": "payload_too_large",
                    "detail": f"Request body exceeds {MAX_BODY_SIZE} bytes limit",
                },
            )
        return await call_next(request)

    # ── 3. Rate limiting ───────────────────────────────────────────────────
    @app.middleware("http")
    async def rate_limit_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not RATE_LIMIT_ENABLED:
            return await call_next(request)

        # Skip rate limiting for static frontend and health
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(("/static/", "/favicon")):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        if not rate_limiter.check(client_ip):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "detail": (
                        f"Too many requests. "
                        f"Limit: {RATE_LIMIT_REQUESTS} per {RATE_LIMIT_WINDOW}s"
                    ),
                },
                headers={"Retry-After": str(RATE_LIMIT_WINDOW)},
            )
        return await call_next(request)
