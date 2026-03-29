"""Simple in-memory sliding window rate limiter."""

import time
from collections import defaultdict

from fastapi import HTTPException, Request


class RateLimiter:
    """In-memory sliding window rate limiter keyed by client IP."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _clean(self, key: str, now: float) -> None:
        cutoff = now - self._window
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]

    async def __call__(self, request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.time()

        self._clean(ip, now)

        if len(self._requests[ip]) >= self._max:
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={"Retry-After": str(self._window)},
            )

        self._requests[ip].append(now)


# Pre-configured limiters for auth endpoints
login_limiter = RateLimiter(max_requests=5, window_seconds=60)
register_limiter = RateLimiter(max_requests=3, window_seconds=60)
