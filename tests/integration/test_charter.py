"""V6.4 the owner's charter: only the owner amends it, tightening is free, loosening needs step-up, every change is
recorded, and the rules are enforced (agent daily cap, mission budget cap, quiet hours)."""
import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from services.core import db
from services.core.events import ORG_ID, transaction
from services.finance import stepup
from services.management import charter
from tests.conftest import mission_status, wait_for
from tests.integration.test_missions import FakeGateway, live_client, start


@pytest.fixture
def fast_totp(monkeypatch):
    monkeypatch.setattr(stepup, "STEP", 1)


def _step_up(client, secret):
    time.sleep(1.05)
    r = client.post("/api/finance/stepup/verify", json={"code": stepup.totp(secret), "purpose": "charter"})
    assert r.status_code == 200, r.text
    return r.json()["step_up_token"]


def test_charter_starts_empty_and_lists_locked_rules(client):
    c = client.get("/api/charter").json()
    assert c["rules"] == {} and c["version"] == 0 and c["amendments"] == []
    assert any("default branch" in r for r in c["locked"]) and any("step-up" in r for r in c["locked"])


def test_tightening_is_free_loosening_needs_step_up_and_all_is_recorded(client, fast_totp):
    r = client.put("/api/charter", json={"agent_daily_usd": 2, "mission_budget_cap_usd": 5, "note": "keep spend small"})
    assert r.status_code == 200, r.text
    assert r.json()["rules"] == {"agent_daily_usd": 2.0, "mission_budget_cap_usd": 5.0} and r.json()["version"] == 1
    # stricter again: still no step-up
    assert client.put("/api/charter", json={"agent_daily_usd": 1, "mission_budget_cap_usd": 5}).json()["version"] == 2
    # raising a cap or dropping one loosens: refused without step-up
    r = client.put("/api/charter", json={"agent_daily_usd": 3, "mission_budget_cap_usd": 5})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "step_up_required"
    assert client.put("/api/charter", json={"mission_budget_cap_usd": 5}).status_code == 401
    secret = client.post("/api/finance/stepup/enroll").json()["secret"]
    r = client.put("/api/charter", json={"agent_daily_usd": 3, "mission_budget_cap_usd": 5}, headers={"X-Step-Up": _step_up(client, secret)})
    assert r.status_code == 200 and r.json()["version"] == 3
    hist = r.json()["amendments"]
    assert [a["version"] for a in hist] == [3, 2, 1]
    assert hist[0]["loosened"] == 1 and hist[0]["step_up_method"] == "totp" and hist[0]["changes"]["agent_daily_usd"] == {"from": 1.0, "to": 3.0}
    assert hist[2]["note"] == "keep spend small" and hist[2]["loosened"] == 0
    assert "charter.amended" in [e["event_type"] for e in client.get("/api/events?after=0").json()["events"]]
    # bad input
    assert client.put("/api/charter", json={"agent_daily_usd": 500}).status_code == 422
    assert client.put("/api/charter", json={"quiet_hours": {"start": "25:00", "end": "07:00"}}).status_code == 422
    assert client.put("/api/charter", json={"agent_daily_usd": 3, "mission_budget_cap_usd": 5,
                                            "quiet_hours": {"start": "22:00", "end": "07:00", "tz": "Mars/Base"}}).status_code == 422


def test_mission_budgets_respect_the_cap(client):
    client.put("/api/charter", json={"mission_budget_cap_usd": 0.5})
    r = client.post("/api/missions", json={"prompt": "Inspect the sample project and fix the failing test.", "budget_usd": 2})
    assert r.status_code == 422 and "caps a mission" in r.json()["detail"]
    r = client.post("/api/missions", json={"prompt": "Inspect the sample project and fix the failing test."})
    assert r.status_code == 201 and r.json()["budget_usd"] <= 0.5  # the default budget is held to the cap
    assert client.patch(f"/api/missions/{r.json()['id']}/budget", json={"budget_usd": 3}).status_code == 422


def test_agent_daily_cap_pauses_work(monkeypatch):
    with live_client(monkeypatch, FakeGateway(cost=0.3)) as client:
        client.put("/api/charter", json={"agent_daily_usd": 0.25})
        mid = start(client, budget_usd=10)
        m = wait_for(lambda: (s := mission_status(client, mid))["paused"] and s)
        assert "under your charter" in m["pause_reason"]


def test_quiet_hours_cross_midnight_and_hold_scheduled_work(client):
    q = {"quiet_hours": {"start": "22:00", "end": "07:00", "tz": "UTC"}}
    at = lambda h, mi=0: datetime(2026, 10, 16, h, mi, tzinfo=timezone.utc)  # noqa: E731
    assert charter.quiet_now(q, at(23)) and charter.quiet_now(q, at(3)) and not charter.quiet_now(q, at(7)) and not charter.quiet_now(q, at(12))
    day = {"quiet_hours": {"start": "09:00", "end": "17:00", "tz": "America/Los_Angeles"}}
    assert charter.quiet_now(day, at(17)) and not charter.quiet_now(day, at(1))  # 10:00 and 18:00 in Los Angeles
    now = datetime.now(timezone.utc)
    start_h = f"{now.hour:02d}:00"
    end_h = f"{(now.hour + 1) % 24:02d}:00"
    client.put("/api/charter", json={"quiet_hours": {"start": start_h, "end": end_h, "tz": "UTC"}})
    with db.get_engine().connect() as conn:
        assert charter.job_waits(conn, "pipeline", ORG_ID) and charter.job_waits(conn, "applab", ORG_ID)
        assert not charter.job_waits(conn, "supervisor", ORG_ID) and not charter.job_waits(conn, "logistics", ORG_ID)
    from services.api.main import state
    res = state.scheduler.run_due(force=True)
    assert res.get("pipeline") == {"waiting": "quiet hours (your charter)"}
    # missions you start yourself still run
    mid = start(client)
    wait_for(lambda: mission_status(client, mid)["status"] in ("WAITING_FOR_APPROVAL", "COMPLETED"))


def test_only_the_owner_amends(client, monkeypatch):
    from services.api import finance
    from fastapi import HTTPException

    def not_owner(p):
        raise HTTPException(403, "requires role owner")
    monkeypatch.setattr(finance, "require_owner", not_owner)
    assert client.put("/api/charter", json={"agent_daily_usd": 1}).status_code == 403
    with transaction() as conn:
        assert conn.execute(select(db.charters)).first() is None
