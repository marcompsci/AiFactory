"""V6.8 least privilege: unused grants are suggested for revocation, only the owner revokes, a revocation survives a
restart (re-seed), and restoring needs step-up."""
import time

import pytest
from sqlalchemy import select

from services.core import db
from services.finance import stepup


@pytest.fixture
def fast_totp(monkeypatch):
    monkeypatch.setattr(stepup, "STEP", 1)


def _first_suggestion(review):
    for a in review["agents"]:
        for g in a["grants"]:
            if g["suggestion"] == "revoke":
                return a, g
    return None, None


def test_review_suggests_only_unused_grants_outside_every_plan(client):
    r = client.get("/api/permissions/review").json()
    assert r["method"] == "records" and r["agents"]
    for a in r["agents"]:
        for g in a["grants"]:
            if g["in_plan"] or g["uses"]:
                assert g["suggestion"] == "keep", (a["agent"], g)
    # the developer's plan tools are never suggested
    dev = next(a for a in r["agents"] if a["role"].lower().startswith("developer") or a["agent"] == "Kade")
    assert not [g for g in dev["grants"] if g["tool"] == "edit_file" and g["suggestion"] == "revoke"]


def test_revoke_survives_a_restart_and_restore_needs_step_up(client, fast_totp):
    a, g = _first_suggestion(client.get("/api/permissions/review").json())
    if a is None:  # every grant is used by some plan in this seed: revoke a plan tool instead (with a warning)
        a = client.get("/api/permissions/review").json()["agents"][0]
        g = a["grants"][0]
    r = client.post("/api/permissions/revoke", json={"agent_id": a["agent_id"], "tool": g["tool"], "reason": "unused"})
    assert r.status_code == 200, r.text
    assert (r.json()["warning"] is None) == (not g["in_plan"])
    assert client.post("/api/permissions/revoke", json={"agent_id": a["agent_id"], "tool": g["tool"]}).status_code == 404  # gone
    db.seed(db.get_engine())  # what a restart does
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.agent_capabilities).where(db.agent_capabilities.c.agent_id == a["agent_id"],
                                                               db.agent_capabilities.c.tool_name == g["tool"])).first() is None
    review = client.get("/api/permissions/review").json()
    rev = next(x for x in review["agents"] if x["agent_id"] == a["agent_id"])["revoked"]
    assert rev and rev[0]["tool_name"] == g["tool"]
    types = [e["event_type"] for e in client.get("/api/events?after=0").json()["events"]]
    assert "permission.revoked" in types

    r = client.post("/api/permissions/restore", json={"revocation_id": rev[0]["id"]})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "step_up_required"
    secret = client.post("/api/finance/stepup/enroll").json()["secret"]
    time.sleep(1.05)
    tok = client.post("/api/finance/stepup/verify", json={"code": stepup.totp(secret), "purpose": "permissions"}).json()["step_up_token"]
    r = client.post("/api/permissions/restore", json={"revocation_id": rev[0]["id"]}, headers={"X-Step-Up": tok})
    assert r.status_code == 200 and r.json()["restored"] == g["tool"]
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.agent_capabilities).where(db.agent_capabilities.c.agent_id == a["agent_id"],
                                                               db.agent_capabilities.c.tool_name == g["tool"])).first() is not None
    assert client.post("/api/permissions/restore", json={"revocation_id": rev[0]["id"]}, headers={"X-Step-Up": tok}).status_code == 409


def test_a_revoked_tool_is_refused_at_run_time(client):
    from services.tools.registry import ToolContext, ToolDenied, execute_tool
    from tests.conftest import wait_for, mission_status
    from tests.integration.test_missions import pending_approval, start
    mid = start(client)
    pending_approval(client, mid)
    detail = client.get(f"/api/missions/{mid}").json()
    inspect = next(t for t in detail["tasks"] if t["key"] == "inspect")
    assert client.post("/api/permissions/revoke", json={"agent_id": inspect["agent_id"], "tool": "inspect_repository"}).status_code == 200
    ctx = ToolContext(mid, inspect["id"], inspect["agent_id"], detail["mission"]["organization_id"], "simulation")
    with pytest.raises(ToolDenied):
        execute_tool(ctx, "inspect_repository", {})
    assert mission_status(client, mid)["status"] == "WAITING_FOR_APPROVAL"
    wait_for(lambda: True)


def test_a_grant_nothing_uses_is_suggested_once_there_is_enough_history(client):
    from sqlalchemy import insert, update
    from services.core.events import transaction
    agent = client.get("/api/permissions/review").json()["agents"][0]
    with transaction() as conn:
        conn.execute(insert(db.agent_capabilities).values(agent_id=agent["agent_id"], tool_name="send_fax"))
    fresh = client.get("/api/permissions/review").json()
    assert fresh["enough_history"] is False and fresh["suggestions"] == 0  # a new install has nothing to judge by
    from services.core.events import emit
    with transaction() as conn:
        emit(conn, "agent.message", payload={"body": "an old record"})
        conn.execute(update(db.events).values(occurred_at="2020-01-01T00:00:00+00:00"))
    r = client.get("/api/permissions/review").json()
    assert r["enough_history"] is True
    g = next(g for a in r["agents"] if a["agent_id"] == agent["agent_id"] for g in a["grants"] if g["tool"] == "send_fax")
    assert g["suggestion"] == "revoke" and "no plan or pipeline" in g["why"]
    assert r["suggestions"] >= 1
