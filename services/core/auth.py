"""Authentication, role checks and rate limiting.

Modes (decided from the environment, see .env.example):
  * dev      — no AICIV_API_TOKEN and no SUPABASE_JWT_SECRET. Single local user with the owner role.
               The API refuses to bind to anything but localhost in this mode (see services/api/main.py).
  * token    — AICIV_API_TOKEN set. Bearer token must match (constant-time compare).
  * supabase — SUPABASE_JWT_SECRET set. Supabase Auth access tokens (HS256, aud=authenticated) are verified;
               the role comes from the token's app_metadata.role (default: viewer).
"""
from __future__ import annotations

import hmac
import threading
import time
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request

from .config import get_settings, load_seed

ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}


@dataclass(frozen=True)
class Principal:
    user_id: str
    organization_id: str
    role: str
    mode: str

    def require(self, role: str) -> None:
        if ROLE_RANK.get(self.role, -1) < ROLE_RANK[role]:
            raise HTTPException(status_code=403, detail=f"requires role {role}")


def _token_from(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    # EventSource cannot send headers, so the stream endpoint alone accepts a query token.
    if request.url.path.endswith("/stream"):
        return request.query_params.get("access_token")
    return None


def authenticate(request: Request) -> Principal:
    s = get_settings()
    org = load_seed()["organization_id"]
    if s.dev_auth:
        return Principal(user_id="00000000-0000-4000-8000-000000000000", organization_id=org, role="owner", mode="dev")
    token = _token_from(request)
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    if s.api_token and hmac.compare_digest(token, s.api_token):
        return Principal(user_id="00000000-0000-4000-8000-000000000001", organization_id=org, role="owner", mode="token")
    if s.supabase_jwt_secret:
        try:
            claims = jwt.decode(token, s.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="invalid token") from exc
        role = (claims.get("app_metadata") or {}).get("role", "viewer")
        return Principal(user_id=claims["sub"], organization_id=org, role=role if role in ROLE_RANK else "viewer", mode="supabase")
    raise HTTPException(status_code=401, detail="invalid token")


class RateLimiter:
    """Token bucket per (principal, bucket). In-process; use Redis in a multi-instance deployment."""

    def __init__(self, rate_per_minute: int = 30, burst: int = 10) -> None:
        self.rate = rate_per_minute / 60.0
        self.burst = burst
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.burst), now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < 1:
                raise HTTPException(status_code=429, detail="rate limit exceeded")
            self._state[key] = (tokens - 1, now)


mutation_limiter = RateLimiter()
