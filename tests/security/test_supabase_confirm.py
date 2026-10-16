"""Sign-in for Supabase projects that sign with the legacy shared secret when this server doesn't have it: the token is
confirmed with Supabase Auth (GET /auth/v1/user). And your own network never locks a phone out in local mode."""
import io
import json
import time
import urllib.error

import jwt
import pytest
from fastapi.testclient import TestClient

from services.core import auth, config, security

URL = "https://proj.supabase.co"
OWNER = "owner@example.com"


def token(sub="33333333-3333-4333-8333-333333333333", **over):
    claims = {"sub": sub, "aud": "authenticated", "iss": URL + "/auth/v1", "exp": int(time.time()) + 600, "email": OWNER, **over}
    return jwt.encode(claims, "the-projects-secret-we-dont-have-here-xxxxxxxx", algorithm="HS256")


@pytest.fixture
def supabase(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("AICIV_OWNER_EMAILS", OWNER)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    config.get_settings.cache_clear()
    auth._confirmed.clear()
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req)
        bearer = req.headers["Authorization"].split(" ", 1)[1]
        assert req.headers["Apikey"] == "sb_publishable_test" and req.full_url == URL + "/auth/v1/user"
        if bearer.endswith("tampered"):
            raise urllib.error.HTTPError(req.full_url, 401, "bad jwt", {}, io.BytesIO(b"{}"))
        sub = jwt.decode(bearer, options={"verify_signature": False})["sub"]
        body = {"id": sub, "email": OWNER, "app_metadata": {"provider": "google"}, "user_metadata": {"email_verified": True}}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return calls


def client():
    from services.api.main import app
    app.state.gateway = None
    return TestClient(app)


def test_tokens_signed_with_the_legacy_secret_are_confirmed_with_supabase(supabase):
    with client() as c:
        t = token()
        r = c.get("/api/play/state", headers={"authorization": f"Bearer {t}"})
        assert r.status_code == 200, r.text
        # the owner (by verified email) can act, e.g. save their character
        assert c.put("/api/play/state", json={}, headers={"authorization": f"Bearer {t}"}).status_code == 200
        assert len(supabase) == 1  # cached: Supabase asked once per token


def test_supabase_refusal_wrong_issuer_and_expiry_are_refused(supabase):
    with client() as c:
        assert c.get("/api/snapshot", headers={"authorization": f"Bearer {token()}tampered"}).status_code == 401
        assert c.get("/api/snapshot", headers={"authorization": f"Bearer {token(iss='https://evil.example/auth/v1')}"}).status_code == 401
        r = c.get("/api/snapshot", headers={"authorization": f"Bearer {token(exp=int(time.time()) - 120)}"})
        assert r.status_code == 401 and r.json()["detail"] == "token expired"


def test_supabase_unreachable_is_503_and_never_locks_you_out(supabase, monkeypatch):
    def down(req, timeout=0):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr("urllib.request.urlopen", down)
    security.auth_failures.clear()
    with client() as c:
        codes = [c.get("/api/snapshot", headers={"authorization": f"Bearer {token()}"}).status_code for _ in range(8)]
    assert set(codes) == {503}


def test_your_own_network_never_triggers_the_lockout_in_local_mode(monkeypatch):
    monkeypatch.setenv("AICIV_LOCAL_MODE", "1")
    for ip in ("127.0.0.1", "::1", "192.168.1.20", "172.20.10.2", "10.0.0.5", "fe80::7880:5bff:fe49:db95", "fd00::1", "::ffff:192.168.1.4"):
        assert auth._counts(ip) is False, ip
    assert auth._counts("8.8.8.8") is True
    monkeypatch.setenv("AICIV_LOCAL_MODE", "0")
    assert auth._counts("192.168.1.20") is True
