"""Per-client rate limiting for the public API.

Allows one request per window per client IP. State is kept in memory, so it
holds per API process: if the API runs as several workers or servers, each
keeps its own counts, and a shared store (e.g. Redis) would be needed for one
limit across them.
"""

import math
import os
import threading
import time

from fastapi import HTTPException, Request, Response

WINDOW_SECONDS = float(os.getenv("PUBLIC_API_WINDOW_SECONDS", "5"))

# Behind a reverse proxy every request comes from the proxy's address, so the
# client IP has to be read from X-Forwarded-For. Only enable this when a proxy
# you control sets that header; otherwise clients can fake it to dodge the limit.
TRUST_FORWARDED_FOR = os.getenv("TRUST_FORWARDED_FOR", "false").lower() == "true"

_last_request: dict[str, float] = {}
_lock = threading.Lock()
_last_cleanup = 0.0


def client_ip(request: Request) -> str:
    if TRUST_FORWARDED_FOR:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, response: Response) -> None:
    """FastAPI dependency: rejects a client's request with 429 if its previous
    accepted request was less than WINDOW_SECONDS ago. Rejected requests don't
    restart the window."""
    global _last_cleanup
    ip = client_ip(request)
    now = time.monotonic()

    with _lock:
        # Forget clients that have been quiet for a while, so memory stays small.
        if now - _last_cleanup > 60:
            for key in [k for k, t in _last_request.items() if now - t > WINDOW_SECONDS]:
                del _last_request[key]
            _last_cleanup = now

        last = _last_request.get(ip)
        if last is not None and now - last < WINDOW_SECONDS:
            retry_after = math.ceil(WINDOW_SECONDS - (now - last))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: 1 request per {WINDOW_SECONDS:g} seconds. "
                f"Try again in {retry_after} s.",
                headers={"Retry-After": str(retry_after)},
            )
        _last_request[ip] = now

    response.headers["X-RateLimit-Limit"] = f"1 per {WINDOW_SECONDS:g}s"
