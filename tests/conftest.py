import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets its own database and workspace directory, and no real credentials."""
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AICIV_API_TOKEN", "SUPABASE_JWT_SECRET", "SUPABASE_URL",
              "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL", "AICIV_SANDBOX"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AICIV_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AICIV_TRAVEL_SECONDS", "0")
    from services.core import config, db

    from services.core import auth

    config.get_settings.cache_clear()
    db.reset_engine()
    auth.mutation_limiter._state.clear()
    from services.orchestrator.graph import reset_checkpointer
    reset_checkpointer()
    yield tmp_path
    db.reset_engine()
    config.get_settings.cache_clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from services.api.main import app

    app.state.gateway = None
    with TestClient(app) as c:
        yield c


def wait_for(fn, timeout=30.0, interval=0.1):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s (last={last!r})")


def mission_status(client, mid):
    return client.get(f"/api/missions/{mid}").json()["mission"]


FIX = json.loads((ROOT / "services/api/sample_repo/.aiciv/known_fix.json").read_text())
