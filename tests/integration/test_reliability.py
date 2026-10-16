"""V6.1 reliability: loops are caught, failures are labeled (MAST), agents learn cited lessons, objectives are checked,
and the town asks instead of guessing."""
from sqlalchemy import insert, select, update

from services.core import db
from services.core.events import transaction
from services.management import reliability
from services.management.supervisor import supervise
from tests.conftest import mission_status, wait_for
from tests.integration.test_missions import FakeGateway, live_client, pending_approval, start
from tests.integration.test_play import ATLAS, KADE, LUMEN, say


def test_error_normalisation_and_labels():
    assert reliability._norm("retrying: timed out after 300s at /tmp/wt/abc123def456") == reliability._norm("timed out after 120s at /x/y")
    assert reliability._mode_for("permission denied: edit_file outside the worktree") == "FM-1.2"
    assert reliability._mode_for("timed out after 300s") == "FM-1.5"
    assert reliability._mode_for("tests still failing after all attempts") == "FM-1.1"
    assert reliability._mode_for("model did not return JSON") == "FM-2.6"
    assert reliability._mode_for("model call failed: provider down") == "INFRA"
    assert reliability._mode_for(f"{reliability.LOOP_PREFIX} 2 times: model call failed: provider down") == "INFRA"
    assert reliability._mode_for(f"{reliability.LOOP_PREFIX} 2 times: wrong file") == "FM-1.3"
    assert reliability._mode_for("something odd") == "UNK"


def test_failures_are_labeled_and_become_cited_lessons(monkeypatch):
    with live_client(monkeypatch, FakeGateway(fail=True)) as client:
        mid = start(client)
        m = wait_for(lambda: (s := mission_status(client, mid))["status"] in ("FAILED", "COMPLETED") and s)
        assert m["status"] == "FAILED"
        detail = client.get(f"/api/missions/{mid}").json()
        impl = next(t for t in detail["tasks"] if t["status"] == "FAILED")
        with db.get_engine().connect() as conn:
            assert "provider down" in (reliability.repeating_failure(conn, impl["id"]) or "")

        clinic = client.get("/api/insights/failures").json()
        assert clinic["method"] == "rules" and clinic["total"] >= 2
        mine = [l for l in clinic["labels"] if l["mission_id"] == mid]
        assert mine and all(l["mode"] == "INFRA" for l in mine)  # an outage is not blamed on the agent's reasoning
        assert all(l["source"].startswith(("task_run:", "task:")) for l in mine)
        assert clinic["by_category"][0]["category"] == "infrastructure" and clinic["advice"]

        # the developer learned a lesson that cites the run it came from, stored as a hypothesis
        dev = client.get(f"/api/agents/{impl['agent_id']}").json()
        assert dev["lessons"] and dev["lessons"][0]["source"].startswith("task_run:") and dev["lessons"][0]["trust"] == "hypothesis"
        assert f"({impl['key']})" in dev["lessons"][0]["lesson"]
        assert any(a["agent_id"] == impl["agent_id"] for a in client.get("/api/insights/lessons").json()["agents"])
        types = [e["event_type"] for e in client.get("/api/events?after=0").json()["events"]]
        assert "agent.lesson_learned" in types

        # lessons are not re-learned twice for the same run
        with transaction() as conn:
            assert reliability.learn_from_mission(conn, mid) == 0


def test_lessons_reach_the_agents_next_prompt(monkeypatch):
    gw = FakeGateway(fail=True)
    with live_client(monkeypatch, gw) as client:
        first = start(client)
        wait_for(lambda: mission_status(client, first)["status"] == "FAILED")
        gw.fail, gw.calls = False, []
        second = start(client)
        pending_approval(client, second)
        prompts = [c.system for c in gw.calls]
        assert any("Lessons from your own earlier runs" in s and "[task_run:" in s for s in prompts)
        assert "agent.lessons_recalled" in [e["event_type"] for e in client.get("/api/events?after=0").json()["events"]]


def test_completed_missions_get_an_objective_check(client):
    mid = start(client)
    a = pending_approval(client, mid)
    client.post(f"/api/approvals/{a['id']}/grant")
    wait_for(lambda: mission_status(client, mid)["status"] == "COMPLETED")
    obj = client.get(f"/api/missions/{mid}").json()["objective"]
    assert obj["met"] is True and obj["findings"]
    with transaction() as conn:  # a finished step that lacks a promised output fails the check
        t = conn.execute(select(db.tasks).where(db.tasks.c.mission_id == mid, db.tasks.c.key == "verify")).first()
        conn.execute(update(db.tasks).where(db.tasks.c.id == t.id).values(outputs={"passed": 5}))
        res = reliability.check_objective(conn, mid)
    assert res["met"] is False and "failed" in res["findings"][0]
    assert client.get(f"/api/missions/{mid}").json()["objective"]["met"] is False
    assert any(l["mode"] == "FM-3.1" for l in client.get("/api/insights/failures").json()["labels"])


def test_supervisor_catches_a_task_repeating_the_same_tool_call(client):
    mid = start(client)
    pending_approval(client, mid)
    with transaction() as conn:
        t = conn.execute(select(db.tasks).where(db.tasks.c.mission_id == mid, db.tasks.c.key == "inspect")).first()
        conn.execute(update(db.tasks).where(db.tasks.c.id == t.id).values(status="RUNNING", updated_at=db.utcnow()))
        for _ in range(reliability.REPEAT_TOOL_LIMIT):
            conn.execute(insert(db.tool_executions).values(id=db.new_id(), organization_id=t.organization_id, mission_id=mid, task_id=t.id,
                                                           agent_id=t.agent_id, tool_name="search_code", arguments={"pattern": "def x"},
                                                           status="COMPLETED"))
        assert supervise(conn)["looping"] == 1
        assert supervise(conn)["looping"] == 0  # recorded once
        conn.execute(update(db.tasks).where(db.tasks.c.id == t.id).values(status="COMPLETED"))
    assert "manager.loop_detected" in [e["event_type"] for e in client.get("/api/events?after=0").json()["events"]]


def test_vague_requests_get_a_question_not_a_proposal(client):
    for text in ("fix it", "fix the bug", "make the app better", "build an app"):
        r = say(client, KADE, text)
        assert r["proposal"] is None and "which part" in r["reply"].lower(), text
    r = say(client, LUMEN, "research stuff")
    assert r["proposal"] is None and "exactly" in r["reply"]
    # a manager asks where to look instead of assuming the App Store
    r = say(client, ATLAS, "research candles")
    assert r["proposal"] is None and "Etsy" in r["reply"] and len(r["suggestions"]) == 2
    assert say(client, ATLAS, r["suggestions"][1])["proposal"]["params"]["source"] == "etsy"
    # a clear request still becomes a proposal
    assert say(client, KADE, "fix the median function so even-length lists average the middle pair")["proposal"]["kind"] == "create_mission"
