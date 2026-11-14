"""API security: API keys, rate limiting and request-size limits (no extra dependencies).

- API key (header X-API-Key) protects endpoints that compute on caller input (POST /predict). Keys come from
  FLARE_API_KEYS (comma-separated, so a new key can be added before the old one is removed: rotation without downtime).
  With no key configured the protected endpoints refuse every request (fail closed).
- Rate limit: a sliding one-minute window per client. Callers with a valid key get their own, larger budget; anonymous
  callers are counted per IP (first X-Forwarded-For hop when the request came through our proxy, see `client_id`).
  /health and /metrics are never limited (probes and Prometheus must always get through).
- Request size: bodies larger than FLARE_MAX_BODY_BYTES are refused with 413 before they are read.
"""

from __future__ import annotations

import hmac
import threading
import time
from collections import deque

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from src.settings import get_settings

EXEMPT = ("/health", "/metrics")
API_KEY_HEADER = "X-API-Key"


def _keys() -> list[str]:
    return [k.strip() for k in get_settings().api_keys.split(",") if k.strip()]


def valid_key(given: str | None) -> bool:
    """Constant-time comparison against every configured key."""
    if not given:
        return False
    return any(hmac.compare_digest(given.encode(), k.encode()) for k in _keys())


def require_api_key(request: Request) -> None:
    """FastAPI dependency for protected endpoints."""
    if not _keys():
        raise HTTPException(401, "API key required, and none is configured on the server (FLARE_API_KEYS)")
    if not valid_key(request.headers.get(API_KEY_HEADER)):
        raise HTTPException(401, f"missing or invalid {API_KEY_HEADER} header", headers={"WWW-Authenticate": "ApiKey"})


def client_id(request: Request) -> str:
    """Rate-limit identity: the API key if valid, else the client IP (proxy-aware when trust_proxy_headers is set)."""
    key = request.headers.get(API_KEY_HEADER)
    if key and valid_key(key):
        return "key:" + hmac.new(b"flare", key.encode(), "sha256").hexdigest()[:16]
    ip = request.client.host if request.client else "unknown"
    if get_settings().trust_proxy_headers:
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            ip = fwd.split(",")[0].strip() or ip
    return "ip:" + ip


class SlidingWindowLimiter:
    """In-memory sliding one-minute window per identity. One process = one budget (each replica counts separately)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, ident: str, limit: int, now: float | None = None) -> tuple[bool, int]:
        """Record one request. Returns (allowed, seconds until a slot frees up)."""
        if limit <= 0:
            return True, 0
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(ident, deque())
            while q and q[0] <= now - 60:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(60 - (now - q[0])) + 1)
            q.append(now)
            if len(self._hits) > 50_000:  # forget idle identities so memory stays bounded
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - 60]:
                    del self._hits[k]
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


LIMITER = SlidingWindowLimiter()


def check_request(request: Request) -> JSONResponse | None:
    """Size and rate checks for one request; returns the error response, or None to continue."""
    s = get_settings()
    path = request.url.path
    if path in EXEMPT:
        return None
    size = request.headers.get("content-length")
    if size is not None and size.isdigit() and int(size) > s.max_body_bytes:
        return JSONResponse({"detail": f"request body larger than {s.max_body_bytes} bytes"}, status_code=413)
    if request.method in ("POST", "PUT", "PATCH") and size is None and request.headers.get("transfer-encoding"):
        return JSONResponse({"detail": "chunked request bodies are not accepted; send Content-Length"}, status_code=411)
    ident = client_id(request)
    limit = s.rate_limit_key_per_minute if ident.startswith("key:") else s.rate_limit_per_minute
    ok, retry = LIMITER.hit(ident, limit)
    if not ok:
        return JSONResponse(
            {"detail": f"rate limit exceeded ({limit} requests per minute)"},
            status_code=429,
            headers={"Retry-After": str(retry)},
        )
    return None
