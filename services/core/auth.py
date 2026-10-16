"""Authentication, role checks and rate limiting.

Modes (decided from the environment, see .env.example):
  * dev      — no AICIV_API_TOKEN and no SUPABASE_JWT_SECRET. Single local user with the owner role.
               The API refuses to bind to anything but localhost in this mode (see services/api/main.py).
  * token    — AICIV_API_TOKEN set. Bearer token must match (constant-time compare).
  * supabase — SUPABASE_URL (asymmetric signing keys, verified against the project's JWKS) and/or
               SUPABASE_JWT_SECRET (legacy HS256). Access tokens (aud=authenticated) are verified; the role comes
               from app_metadata.role, else a verified email in AICIV_OWNER_EMAILS, else viewer.
"""
from __future__ import annotations

import hmac
import logging
import threading
import time
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request

from .config import get_settings, load_seed

log = logging.getLogger("aiciv.auth")

ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}


@dataclass(frozen=True)
class Principal:
    user_id: str
    organization_id: str
    role: str
    mode: str
    mfa_fresh: bool = False  # Supabase session at aal2 with a recent MFA verification (step-up for financial approvals)

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


_jwks: dict[str, "jwt.PyJWKClient"] = {}


def _tls():
    """Certificates for talking to Supabase. Python from python.org on a Mac ships without any (until "Install
    Certificates" is run), which made every signing-key download fail; certifi's bundle always works."""
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _publishable_key() -> str:
    import os

    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "") or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")
    return key if key.startswith(("sb_publishable_", "eyJ")) else ""


_confirmed: dict[str, tuple[float, dict]] = {}   # sha256(token) -> (valid until, claims)
_confirmed_lock = threading.Lock()


def confirm_with_supabase(token: str, supabase_url: str, issuer: str | None) -> dict:
    """For tokens this server can't check itself (projects that sign with the legacy shared secret, when
    SUPABASE_JWT_SECRET isn't set here): ask Supabase Auth who the token belongs to (GET /auth/v1/user). Supabase checks
    the signature; we use its answer, including app_metadata, which only the service key can write. Answers are
    cached for a few minutes per token (by hash), never past the token's expiry."""
    import hashlib
    import json
    import urllib.error
    import urllib.request

    key = _publishable_key()
    if not (supabase_url and key):
        raise HTTPException(status_code=401, detail="invalid token")
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    now = time.time()
    if float(payload.get("exp", 0)) < now - 30:
        raise HTTPException(status_code=401, detail="token expired")
    if payload.get("aud") != "authenticated" or (issuer and payload.get("iss") != issuer) or not payload.get("sub"):
        log.info("token refused: wrong audience or issuer")
        raise HTTPException(status_code=401, detail="invalid token")
    h = hashlib.sha256(token.encode()).hexdigest()
    with _confirmed_lock:
        hit = _confirmed.get(h)
        if hit and hit[0] > now:
            return hit[1]
    req = urllib.request.Request(supabase_url.rstrip("/") + "/auth/v1/user",
                                 headers={"apikey": key, "Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8, context=_tls()) as resp:  # noqa: S310 (fixed https Supabase address from config)
            user = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            log.info("token refused by Supabase (%s)", exc.code)
            raise HTTPException(status_code=401, detail="invalid token") from exc
        raise HTTPException(status_code=503, detail="can't check sign-in with Supabase right now") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("can't reach Supabase to check a sign-in: %s", exc)
        raise HTTPException(status_code=503, detail="can't check sign-in with Supabase right now") from exc
    if user.get("id") != payload.get("sub"):
        raise HTTPException(status_code=401, detail="invalid token")
    claims = {**payload, "email": user.get("email") or payload.get("email"),
              "app_metadata": user.get("app_metadata") or {}, "user_metadata": user.get("user_metadata") or {}}
    with _confirmed_lock:
        if len(_confirmed) > 500:
            _confirmed.clear()
        _confirmed[h] = (min(float(payload["exp"]), now + 300), claims)
    return claims


def verify_supabase_token(token: str, secret: str, jwks_url: str, issuer: str | None = None, supabase_url: str = "") -> dict:
    """HS256 with the legacy shared secret, or ES256/RS256 against the project's published signing keys. Tokens must
    carry `exp` and `sub`, be for `aud=authenticated`, and (when SUPABASE_URL is set) come from this project's issuer.
    A token this server can't check locally (HS256 without the secret here, or a key it doesn't have) is confirmed
    with Supabase Auth instead."""
    opts = {"require": ["exp", "sub"]}
    kw = {"audience": "authenticated", "options": opts, "leeway": 30}
    if issuer:
        kw["issuer"] = issuer
    try:
        if len(token) > 8192:
            raise jwt.InvalidTokenError("token too large")
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "HS256":
            if not secret:
                return confirm_with_supabase(token, supabase_url, issuer)
            return jwt.decode(token, secret, algorithms=["HS256"], **kw)
        if alg not in ("ES256", "RS256") or not jwks_url:
            raise jwt.InvalidTokenError("unsupported token algorithm")
        client = _jwks.get(jwks_url) or _jwks.setdefault(jwks_url, jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600, timeout=10, ssl_context=_tls()))
        try:
            key = client.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError as exc:
            log.warning("couldn't load Supabase signing keys (%s); confirming the sign-in with Supabase instead", exc)
            return confirm_with_supabase(token, supabase_url, issuer)
        return jwt.decode(token, key, algorithms=[alg], **kw)
    except jwt.ExpiredSignatureError as exc:
        # correctly signed but old: a stale session, not an attack (never counts toward the lockout)
        raise HTTPException(status_code=401, detail="token expired") from exc
    except jwt.PyJWTError as exc:
        log.info("token refused: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="invalid token") from exc


def owner_by_email(claims: dict) -> str | None:
    """Sign in with Google / GitHub: map the owner by a *verified* email listed in AICIV_OWNER_EMAILS. `app_metadata.role`
    (writable only with the Supabase service key) always wins; everyone else is a viewer until given a role."""
    import os

    allowed = {e.strip().lower() for e in os.environ.get("AICIV_OWNER_EMAILS", "").split(",") if e.strip()}
    email = str(claims.get("email") or "").lower()
    verified = bool((claims.get("user_metadata") or {}).get("email_verified"))
    return "owner" if email and verified and email in allowed else None


def authenticate(request: Request) -> Principal:
    s = get_settings()
    org = load_seed()["organization_id"]
    if s.dev_auth:
        return Principal(user_id="00000000-0000-4000-8000-000000000000", organization_id=org, role="owner", mode="dev")
    token = _token_from(request)
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    from .security import auth_failures

    client = request.client.host if request.client else "unknown"
    if s.api_token and hmac.compare_digest(token.encode(), s.api_token.encode()):
        auth_failures.succeed(client)
        return Principal(user_id="00000000-0000-4000-8000-000000000001", organization_id=org, role="owner", mode="token")
    if s.supabase_jwt_secret or s.supabase_jwks_url:
        try:
            claims = verify_supabase_token(token, s.supabase_jwt_secret, s.supabase_jwks_url, issuer=_issuer(s.supabase_url),
                                           supabase_url=s.supabase_url)
        except HTTPException as exc:
            # only a refused token counts toward the lockout (not an expired one, and not Supabase being unreachable)
            if exc.detail == "invalid token" and _counts(client) and auth_failures.fail(client):
                log.warning("auth lockout for client %s after repeated invalid tokens", client)
            raise
        auth_failures.succeed(client)
        role = (claims.get("app_metadata") or {}).get("role") or owner_by_email(claims) or "viewer"
        from services.finance.stepup import aal2_fresh

        return Principal(user_id=claims["sub"], organization_id=org, role=role if role in ROLE_RANK else "viewer", mode="supabase",
                         mfa_fresh=aal2_fresh(claims))
    if _counts(client):
        auth_failures.fail(client)
    raise HTTPException(status_code=401, detail="invalid token")


def _counts(client: str) -> bool:
    """Bad tokens count toward the lockout, except when running locally (AICIV_LOCAL_MODE=1, set by
    scripts/run-local.sh) and the request comes from this computer or your own network (Wi-Fi, the phone's hotspot):
    a phone with a stale sign-in must not lock itself out at home. Tokens are signed, so guessing one is hopeless anyway."""
    import ipaddress
    import os

    if os.environ.get("AICIV_LOCAL_MODE") != "1":
        return True
    try:
        ip = ipaddress.ip_address(client.split("%")[0])
    except ValueError:
        return True
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return not (ip.is_loopback or ip.is_private or ip.is_link_local)


def _issuer(supabase_url: str) -> str | None:
    return supabase_url.rstrip("/") + "/auth/v1" if supabase_url else None


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
