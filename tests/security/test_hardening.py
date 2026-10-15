"""Backend hardening: headers, body caps, throttling, token rules, and a role matrix over every mutating route."""
import re
import subprocess
import time
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from services.core import config, security

SECRET = "s" * 40
ROOT = Path(__file__).resolve().parents[2]


def token(role: str = "viewer", **over) -> str:
    claims = {"sub": "22222222-2222-4222-8222-222222222222", "aud": "authenticated", "exp": int(time.time()) + 600,
              "app_metadata": {"role": role}, **over}
    return jwt.encode(claims, SECRET, algorithm="HS256")


@pytest.fixture
def jwt_mode(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    config.get_settings.cache_clear()


def client():
    from services.api.main import app
    app.state.gateway = None
    return TestClient(app)


def test_security_headers_on_every_response():
    with client() as c:
        r = c.get("/api/health")
        h = r.headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer" and "default-src 'none'" in h["content-security-policy"]
        assert h["cache-control"] == "no-store" and re.fullmatch(r"[0-9a-f]{16}", h["x-request-id"])
        assert "strict-transport-security" not in h  # plain http in tests
        r = c.get("/api/health", headers={"x-forwarded-proto": "https"})
        assert r.headers["strict-transport-security"].startswith("max-age=")


def test_oversized_bodies_are_refused(monkeypatch):
    with client() as c:
        r = c.post("/api/missions", content=b"x" * 1_100_000, headers={"content-type": "application/json"})
        assert r.status_code == 413 and r.json()["detail"] == "request body too large"

        def chunks():  # no content-length: still capped while streaming
            for _ in range(12):
                yield b"y" * 100_000
        r = c.post("/api/missions", content=chunks(), headers={"content-type": "application/json"})
        assert r.status_code == 413


def test_tokens_must_be_unexpired_signed_and_for_this_audience(jwt_mode):
    with client() as c:
        ok = c.get("/api/snapshot", headers={"authorization": f"Bearer {token()}"})
        assert ok.status_code == 200
        for bad in (token(exp=int(time.time()) - 120),                       # expired
                    token(aud="someone-else"),                                 # wrong audience
                    jwt.encode({"sub": "x", "aud": "authenticated", "app_metadata": {"role": "owner"}}, SECRET, "HS256"),  # no exp
                    jwt.encode({"sub": "x", "aud": "authenticated", "exp": 4102444800}, "w" * 40, "HS256"),  # wrong key
                    jwt.encode({"sub": "x", "aud": "authenticated", "exp": 4102444800}, None, "none")):         # alg=none
            assert c.get("/api/snapshot", headers={"authorization": f"Bearer {bad}"}).status_code == 401, bad


def test_issuer_is_enforced_when_supabase_url_is_set(jwt_mode, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_JWKS_URL", "https://proj.supabase.co/auth/v1/.well-known/jwks.json")
    config.get_settings.cache_clear()
    with client() as c:
        good = token(iss="https://proj.supabase.co/auth/v1")
        assert c.get("/api/snapshot", headers={"authorization": f"Bearer {good}"}).status_code == 200
        other = token(iss="https://attacker.supabase.co/auth/v1")
        assert c.get("/api/snapshot", headers={"authorization": f"Bearer {other}"}).status_code == 401


def test_repeated_bad_tokens_lock_out_the_client(jwt_mode):
    with client() as c:
        for _ in range(10):
            assert c.get("/api/snapshot", headers={"authorization": "Bearer nope.nope.nope"}).status_code == 401
        r = c.get("/api/snapshot", headers={"authorization": f"Bearer {token()}"})  # even a good token waits it out
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_request_budget_per_client(monkeypatch):
    monkeypatch.setattr(security.request_budget, "per_minute", 5)
    with client() as c:
        codes = [c.get("/api/health").status_code for _ in range(7)]
        assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]


def test_step_up_codes_lock_after_five_wrong_tries():
    with client() as c:
        c.post("/api/finance/stepup/enroll")
        codes = [c.post("/api/finance/stepup/verify", json={"code": "000000", "purpose": "x-test"}).status_code for _ in range(6)]
        assert codes[:5] == [401] * 5 and codes[5] == 429


def test_api_docs_are_off_outside_dev_mode():
    from services.api.main import app
    # the app object was built in dev mode for the test run; production builds pass docs_url=None
    src = (ROOT / "services/api/main.py").read_text()
    assert 'docs_url="/docs" if _dev else None' in src and 'openapi_url="/openapi.json" if _dev else None' in src
    assert app.title


def _mutating_routes():
    from fastapi.routing import APIRoute

    from services.api.main import app

    def walk(routes):
        for r in routes:
            if isinstance(r, APIRoute):
                yield r
            elif hasattr(r, "original_router"):  # FastAPI wraps included routers
                yield from walk(r.original_router.routes)
            elif hasattr(r, "routes"):
                yield from walk(r.routes)

    for r in walk(app.routes):
        if r.path.startswith("/api/") and r.methods & {"POST", "PUT", "PATCH", "DELETE"}:
            path = re.sub(r"\{[^}]+\}", "00000000-0000-4000-8000-000000000000", r.path)
            for m in sorted(r.methods & {"POST", "PUT", "PATCH", "DELETE"}):
                yield m, path


def test_no_mutating_route_accepts_anonymous_or_viewer_requests(jwt_mode):
    """Every POST/PUT/PATCH/DELETE under /api needs at least an operator; owner-only routes refuse admins too."""
    routes = list(_mutating_routes())
    assert len(routes) > 40
    with client() as c:
        for method, path in routes:
            anon = c.request(method, path, json={})
            assert anon.status_code == 401, (method, path, anon.status_code)
            viewer = c.request(method, path, json={}, headers={"authorization": f"Bearer {token('viewer')}"})
            assert viewer.status_code == 403, (method, path, viewer.status_code, viewer.text[:120])


def test_no_secrets_are_committed():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    pattern = re.compile(r"(sk-ant-api\d\d-[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}|-----BEGIN (RSA |EC )?PRIVATE KEY-----"
                         r"|AKIA[0-9A-Z]{16}|sb_secret_[A-Za-z0-9_\-]{20,}|GOCSPX-[A-Za-z0-9_\-]{20,})")
    hits = []
    for f in files:
        p = ROOT / f
        if p.suffix in (".png", ".jpg", ".ico", ".lock") or not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        for m in pattern.finditer(p.read_text(errors="ignore")):
            if f.startswith("tests/") and ("Z" * 20 in m.group(0) or "x" * 20 in m.group(0)):
                continue  # obviously fake values used by tests
            hits.append(f"{f}: {m.group(0)[:12]}…")
    assert not hits, hits


def test_public_config_exposes_only_public_values(client, monkeypatch):
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_example")
    r = client.get("/api/public-config")
    assert r.status_code == 200
    assert set(r.json()) == {"supabase_url", "supabase_publishable_key"}
    assert r.json()["supabase_publishable_key"] == "sb_publishable_example"
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_secret_should_never_leak")
    assert client.get("/api/public-config").json()["supabase_publishable_key"] == ""


def test_lan_origins_only_when_serving_the_phone():
    import re

    from services.api.main import LAN_ORIGIN_RX
    rx = re.compile(LAN_ORIGIN_RX)
    for ok in ("http://192.168.1.20:3000", "http://192.0.0.2:3000", "http://172.20.10.3:3000", "http://10.0.0.5:3000", "http://omaris-mac.local:3000"):
        assert rx.match(ok), ok
    for bad in ("http://evil.com:3000", "https://192.168.1.20:3000", "http://192.168.1.20:8000", "http://8.8.8.8:3000",
                "http://192.168.1.20.evil.com:3000", "http://172.32.0.1:3000"):
        assert not rx.match(bad), bad
