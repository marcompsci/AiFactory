import json
import os
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
              "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL", "AICIV_SANDBOX", "AICIV_GITHUB_REPO", "GITHUB_TOKEN", "AICIV_GITHUB_AUTH",
              "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH", "GITHUB_APP_INSTALLATION_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AICIV_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AICIV_TRAVEL_SECONDS", "0")
    from services.core import config, db

    pg_url = os.environ.get("AICIV_TEST_DATABASE_URL")
    if pg_url:  # run the whole suite against real Postgres (CI does this; see TESTING.md)
        monkeypatch.setenv("DATABASE_URL", pg_url)

    from services.core import auth

    config.get_settings.cache_clear()
    db.reset_engine()
    auth.mutation_limiter._state.clear()
    from services.orchestrator.graph import reset_checkpointer
    reset_checkpointer()
    if pg_url:
        from services.core.pg import migrate, truncate_all

        migrate(db.get_engine())
        truncate_all(db.get_engine())
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
