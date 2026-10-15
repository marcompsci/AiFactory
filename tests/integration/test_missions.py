"""Integration tests: real database, real worker, real sandboxed tools against the sample repository."""
import json

import jsonschema
import pytest
from fastapi.testclient import TestClient

from services.core import config
from services.model_gateway.gateway import ModelResponse, ProviderError
from tests.conftest import FIX, ROOT, mission_status, wait_for

PROMPT = "Inspect the sample project, find a failing test, implement a fix, rerun the tests, and prepare a reviewable code change."
SCHEMA = json.loads((ROOT / "packages/event-contracts/schema/event-envelope.v1.json").read_text())


class FakeGateway:
    """Stands in for a model provider in tests. Returns a scripted patch; counts calls and tokens."""

    def __init__(self, patch=None, fail=False, cost=0.001):
        self.patch = patch if patch is not None else {**FIX, "explanation": "median of an even list must average the middle pair"}
        self.fail = fail
        self.cost = cost
        self.calls = []

    available = True

    def complete(self, req, preferred_provider="anthropic"):
        self.calls.append(req)
        if self.fail:
            raise ProviderError("server", "provider down", "anthropic")
        text = json.dumps(self.patch) if "Return ONLY JSON" in req.prompt else "Looks fine."
        return ModelResponse(text, "anthropic", "test-model", 1200, 300, self.cost, 5)


def live_client(monkeypatch, gateway):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    config.get_settings.cache_clear()
    from services.api.main import app
    app.state.gateway = gateway
    return TestClient(app)


def start(client, **kw):
    r = client.post("/api/missions", json={"prompt": PROMPT, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def pending_approval(client, mid):
    return wait_for(lambda: next((a for a in client.get("/api/snapshot").json()["approvals"] if a["mission_id"] == mid), None))


def test_simulation_mission_end_to_end(client):
    mid = start(client)
    m = wait_for(lambda: (s := mission_status(client, mid))["status"] == "WAITING_FOR_APPROVAL" and s)
    assert m["execution_mode"] == "simulation"
    detail = client.get(f"/api/missions/{mid}").json()
    tasks = {t["key"]: t for t in detail["tasks"]}
    assert tasks["reproduce"]["outputs"]["failing_tests"] == ["tests/test_stats.py::test_median_even"]
    assert tasks["implement"]["outputs"]["patch_source"] == "fixture"
    assert tasks["verify"]["outputs"]["failed"] == 0 and tasks["verify"]["outputs"]["passed"] == 5
    assert tasks["publish"]["status"] == "WAITING_FOR_APPROVAL"
    # the protected tool has not run
    assert not [t for t in detail["tool_executions"] if t["tool_name"] == "prepare_pull_request"]

    a = pending_approval(client, mid)
    assert client.post(f"/api/approvals/{a['id']}/grant").status_code == 200
    m = wait_for(lambda: (s := mission_status(client, mid))["status"] == "COMPLETED" and s)
    assert m["outcome"] == "published"
    detail = client.get(f"/api/missions/{mid}").json()
    kinds = {x["kind"] for x in detail["artifacts"]}
    assert {"diff", "test_report", "patch", "note"} <= kinds
    diff = next(x for x in detail["artifacts"] if x["kind"] == "diff")
    content = client.get(f"/api/artifacts/{diff['id']}").json()["content"]
    assert "+    return (ordered[mid - 1] + ordered[mid]) / 2" in content
    # messages are labeled as simulation, never passed off as model output
    assert any("[simulation" in msg["body"] for msg in detail["messages"])
    # every agent is back to IDLE
    assert all(a["execution_state"] == "IDLE" for a in client.get("/api/snapshot").json()["agents"])
    # verified memory cites a tool execution
    mem = client.get("/api/memory").json()["entries"]
    assert any(e["trust"] == "verified" and e["source"].startswith("tool_execution:") for e in mem)
    assert any(e["trust"] == "hypothesis" for e in mem)


def test_events_are_ordered_valid_and_published(client):
    mid = start(client)
    pending_approval(client, mid)
    events = client.get("/api/events?after=0").json()["events"]
    seqs = [e["sequence"] for e in events]
    assert seqs == list(range(1, len(seqs) + 1)), "global sequence must be gapless and ordered"
    for e in events:
        jsonschema.validate(e, SCHEMA)
    types = [e["event_type"] for e in events]
    for t in ["mission.created", "mission.started", "task.assigned", "task.started", "agent.movement_requested", "agent.arrived",
              "tool.started", "tool.completed", "agent.message", "artifact.created", "approval.requested"]:
        assert t in types, t
    # replay from the middle returns exactly the tail (background ticks may have appended more since)
    tail = [e["sequence"] for e in client.get(f"/api/events?after={seqs[10]}").json()["events"]]
    assert tail[:len(seqs) - 11] == seqs[11:] and tail == list(range(seqs[11], seqs[11] + len(tail)))
    # the outbox drains (every event handed to the realtime layer)
    wait_for(lambda: client.get("/api/health").json()["outbox_backlog"] == 0)


def test_rejecting_publication_skips_it(client):
    mid = start(client)
    a = pending_approval(client, mid)
    client.post(f"/api/approvals/{a['id']}/reject")
    m = wait_for(lambda: (s := mission_status(client, mid))["status"] == "COMPLETED" and s)
    assert m["outcome"] == "not_published"
    detail = client.get(f"/api/missions/{mid}").json()
    assert not [t for t in detail["tool_executions"] if t["tool_name"] == "prepare_pull_request"]
    assert client.post(f"/api/approvals/{a['id']}/grant").status_code == 409


def test_protected_tool_denied_without_approval(client):
    from services.tools.registry import ToolContext, ToolDenied, execute_tool
    mid = start(client)
    pending_approval(client, mid)
    detail = client.get(f"/api/missions/{mid}").json()
    publish = next(t for t in detail["tasks"] if t["key"] == "publish")
    ctx = ToolContext(mid, publish["id"], publish["agent_id"], detail["mission"]["organization_id"], "simulation")
    with pytest.raises(ToolDenied, match="no granted approval"):
        execute_tool(ctx, "prepare_pull_request", {"title": "x", "body": "y"})
    rows = client.get(f"/api/missions/{mid}").json()["tool_executions"]
    assert any(r["tool_name"] == "prepare_pull_request" and r["status"] == "DENIED" for r in rows)


def test_unauthorized_tool_request_is_denied_and_audited(client):
    from services.tools.registry import ToolContext, ToolDenied, execute_tool
    mid = start(client)
    pending_approval(client, mid)
    detail = client.get(f"/api/missions/{mid}").json()
    inspect = next(t for t in detail["tasks"] if t["key"] == "inspect")
    ctx = ToolContext(mid, inspect["id"], inspect["agent_id"], detail["mission"]["organization_id"], "simulation")
    # architect has no edit_file capability, and the task does not permit it either
    with pytest.raises(ToolDenied):
        execute_tool(ctx, "edit_file", {"path": "calc/stats.py", "old": "a", "new": "b"})
    # an agent cannot act on another agent's task
    dev = next(t for t in detail["tasks"] if t["key"] == "implement")
    with pytest.raises(ToolDenied, match="does not belong"):
        execute_tool(ToolContext(mid, dev["id"], inspect["agent_id"], ctx.org_id, "simulation"), "read_file", {"path": "README.md"})


def test_cancel_mission(client):
    mid = start(client)
    pending_approval(client, mid)
    assert client.post(f"/api/missions/{mid}/cancel").status_code == 200
    m = mission_status(client, mid)
    assert m["status"] == "CANCELLED"
    snap = client.get("/api/snapshot").json()
    assert not [a for a in snap["approvals"] if a["mission_id"] == mid]


def test_idempotent_creation(client):
    a = client.post("/api/missions", json={"prompt": PROMPT, "idempotency_key": "same"}).json()
    b = client.post("/api/missions", json={"prompt": PROMPT, "idempotency_key": "same"}).json()
    assert a["id"] == b["id"]


def test_emergency_stop_blocks_everything(client):
    mid = start(client)
    pending_approval(client, mid)
    r = client.post("/api/emergency-stop", json={"engaged": True}).json()
    assert mid in r["cancelled"]
    assert client.post("/api/missions", json={"prompt": PROMPT}).status_code == 409
    assert client.get("/api/health").json()["emergency_stopped"] is True
    client.post("/api/emergency-stop", json={"engaged": False})
    assert client.post("/api/missions", json={"prompt": PROMPT}).status_code == 201


def test_live_mode_uses_model_patch_and_records_cost(monkeypatch):
    gw = FakeGateway()
    with live_client(monkeypatch, gw) as client:
        mid = start(client)
        m = wait_for(lambda: (s := mission_status(client, mid))["status"] == "WAITING_FOR_APPROVAL" and s)
        assert m["execution_mode"] == "live"
        detail = client.get(f"/api/missions/{mid}").json()
        impl = next(t for t in detail["tasks"] if t["key"] == "implement")
        assert impl["outputs"]["patch_source"] == "model"
        assert detail["usage"] and all(u["provider_reported_cost_usd"] is None for u in detail["usage"])
        assert m["spent_usd_estimated"] == pytest.approx(0.001 * len(detail["usage"]))
        # untrusted repository content is fenced, including the prompt-injection canary in README
        fix_prompt = next(c.prompt for c in gw.calls if "Return ONLY JSON" in c.prompt)
        assert "<untrusted>" in fix_prompt
        costs = client.get("/api/costs").json()
        assert costs["today_estimated_usd"] > 0 and "Estimated" in costs["note"]


def test_model_cannot_make_tests_pass_by_editing_tests(monkeypatch):
    evil = {"path": "tests/test_stats.py", "old": "== 2.5", "new": "== 3", "explanation": "adjust expectation"}
    with live_client(monkeypatch, FakeGateway(patch=evil)) as client:
        mid = start(client)
        m = wait_for(lambda: (s := mission_status(client, mid))["status"] in ("FAILED", "COMPLETED") and s)
        assert m["status"] == "FAILED"
        detail = client.get(f"/api/missions/{mid}").json()
        assert not [t for t in detail["tool_executions"] if t["tool_name"] == "edit_file"]


def test_provider_failure_fails_mission_honestly(monkeypatch):
    with live_client(monkeypatch, FakeGateway(fail=True)) as client:
        mid = start(client)
        m = wait_for(lambda: (s := mission_status(client, mid))["status"] in ("FAILED", "COMPLETED") and s)
        assert m["status"] == "FAILED" and "failed after 2 attempt(s)" in m["failure_reason"]  # retried, then gave up
        detail = client.get(f"/api/missions/{mid}").json()
        assert not [a for a in detail["artifacts"] if a["kind"] == "patch"]


def test_budget_exhaustion_suspends_mission(monkeypatch):
    with live_client(monkeypatch, FakeGateway(cost=0.4)) as client:
        mid = start(client, budget_usd=0.5)
        m = wait_for(lambda: (s := mission_status(client, mid))["paused"] and s)
        assert "budget" in m["pause_reason"]
        assert m["status"] not in ("COMPLETED",)
        client.patch(f"/api/missions/{mid}/budget", json={"budget_usd": 10})
        client.post(f"/api/missions/{mid}/resume")
        wait_for(lambda: mission_status(client, mid)["status"] == "WAITING_FOR_APPROVAL")


def test_recovery_after_worker_interruption(monkeypatch, isolated_env):
    """Simulate a crash mid-task: rows say RUNNING, nobody is working. A new process must finish the mission."""
    from sqlalchemy import update

    from services.api.main import app
    from services.core import db
    from services.core.events import transaction

    app.state.gateway = None
    with TestClient(app) as client:
        mid = start(client)
        pending_approval(client, mid)
        detail = client.get(f"/api/missions/{mid}").json()
    review = next(t for t in detail["tasks"] if t["key"] == "review")
    with transaction() as conn:  # rewind the mission to "review was running when the process died"
        conn.execute(update(db.missions).where(db.missions.c.id == mid).values(status="RUNNING"))
        conn.execute(update(db.tasks).where(db.tasks.c.mission_id == mid, db.tasks.c.key.in_(["review", "publish", "archive"]))
                     .values(status="PENDING"))
        conn.execute(update(db.tasks).where(db.tasks.c.id == review["id"]).values(status="RUNNING"))
        conn.execute(update(db.approvals).where(db.approvals.c.mission_id == mid).values(status="EXPIRED"))
        conn.execute(db.task_runs.insert().values(id=db.new_id(), organization_id=detail["mission"]["organization_id"],
                                                  task_id=review["id"], attempt=99, status="RUNNING"))
    with TestClient(app) as client:  # "restart": lifespan runs recover()
        wait_for(lambda: mission_status(client, mid)["status"] == "WAITING_FOR_APPROVAL")
        runs = client.get(f"/api/missions/{mid}").json()["task_runs"]
        assert any(r["error"] == "worker interrupted" for r in runs)


def test_reconnecting_client_can_hydrate_and_replay(client):
    mid = start(client)
    wait_for(lambda: mission_status(client, mid)["status"] == "WAITING_FOR_APPROVAL")
    snap = client.get("/api/snapshot").json()
    assert snap["sequence"] > 0 and len(snap["agents"]) == 16 and len(snap["districts"]) == 8  # V5: + 7 finance agents, AI Central Bank
    # whatever happened after the snapshot is exactly what replay returns, in order (background ticks may add events)
    later = [e["sequence"] for e in client.get(f"/api/events?after={snap['sequence']}").json()["events"]]
    assert later == list(range(snap["sequence"] + 1, snap["sequence"] + 1 + len(later)))
    assert next(m for m in snap["missions"] if m["id"] == mid)["status"] == "WAITING_FOR_APPROVAL"


def test_remote_clients_refused_in_dev_mode():
    # TestClient's host is "testclient"; simulate a LAN address instead
    from services.api import main
    from starlette.testclient import TestClient as TC
    with TC(main.app, client=("192.168.1.20", 5000)) as c:
        assert c.get("/api/health").status_code == 403


def test_missions_run_as_langgraph_threads_with_approval_interrupts(client):
    mid = start(client)
    a = pending_approval(client, mid)
    g = client.get(f"/api/missions/{mid}/graph").json()
    assert g["engine"] == "langgraph" and g["thread_id"] == mid
    assert g["next"] == ["await_approval"], g
    assert g["interrupts"] == [{"mission_id": mid, "waiting_for": "approval"}]
    assert g["checkpoints"] >= 4  # input, prepare, at least one execute wave, the interrupt
    client.post(f"/api/approvals/{a['id']}/grant")
    wait_for(lambda: mission_status(client, mid)["status"] == "COMPLETED")
    g2 = client.get(f"/api/missions/{mid}/graph").json()
    assert g2["next"] == [] and g2["values"]["outcome"] == "COMPLETED"
    assert g2["checkpoints"] > g["checkpoints"]
    sources = [s["source"] for s in g2["steps"]]
    assert "input" in sources and "loop" in sources


def test_graph_checkpoint_survives_process_restart(monkeypatch, isolated_env):
    """The interrupt is stored in the checkpointer, so a brand-new process resumes the same graph thread."""
    from services.api.main import app
    from services.orchestrator.graph import reset_checkpointer

    app.state.gateway = None
    with TestClient(app) as c:
        mid = start(c)
        a = pending_approval(c, mid)
        before = c.get(f"/api/missions/{mid}/graph").json()
    reset_checkpointer()  # new process: no in-memory graph state
    with TestClient(app) as c:
        assert c.get(f"/api/missions/{mid}/graph").json()["next"] == ["await_approval"]
        c.post(f"/api/approvals/{a['id']}/grant")
        wait_for(lambda: mission_status(c, mid)["status"] == "COMPLETED")
        after = c.get(f"/api/missions/{mid}/graph").json()
    assert after["checkpoints"] > before["checkpoints"]
