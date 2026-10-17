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


EVIL = {"path": "tests/test_stats.py", "old": "== 2.5", "new": "== 3", "explanation": "adjust expectation"}


def test_outages_are_labeled_but_not_blamed_on_the_agent(monkeypatch):
    with live_client(monkeypatch, FakeGateway(fail=True)) as client:
        mid = start(client)
        assert wait_for(lambda: (s := mission_status(client, mid))["status"] in ("FAILED", "COMPLETED") and s)["status"] == "FAILED"
        clinic = client.get("/api/insights/failures").json()
        mine = [l for l in clinic["labels"] if l["mission_id"] == mid]
        assert clinic["method"] == "rules" and mine and all(l["mode"] == "INFRA" for l in mine)
        assert clinic["by_category"][0]["category"] == "infrastructure" and clinic["incidents"] <= clinic["total"]
        failed = next(t for t in client.get(f"/api/missions/{mid}").json()["tasks"] if t["status"] == "FAILED")
        with db.get_engine().connect() as conn:
            assert reliability.repeating_failure(conn, failed["id"]) is None  # an outage is not a loop
        assert client.get(f"/api/agents/{failed['agent_id']}").json()["lessons"] == []  # nor a lesson


def test_a_repeated_mistake_is_stopped_labeled_and_learned(monkeypatch):
    with live_client(monkeypatch, FakeGateway(patch=EVIL)) as client:
        mid = start(client)
        assert wait_for(lambda: (s := mission_status(client, mid))["status"] in ("FAILED", "COMPLETED") and s)["status"] == "FAILED"
        impl = next(t for t in client.get(f"/api/missions/{mid}").json()["tasks"] if t["key"] == "implement")
        with db.get_engine().connect() as conn:
            d = conn.execute(select(db.manager_decisions).where(db.manager_decisions.c.subject_id == impl["id"],
                                                                db.manager_decisions.c.outcome == "loop_stopped")).first()
        assert d is not None and "refusing to edit tests" in d.rationale
        types = [e["event_type"] for e in client.get("/api/events?after=0").json()["events"]]
        assert "manager.loop_detected" in types and "agent.lesson_learned" in types

        clinic = client.get("/api/insights/failures").json()
        modes = {l["mode"] for l in clinic["labels"] if l["task_id"] == impl["id"]}
        assert modes == {"FM-1.2"}  # editing tests to pass is outside the developer's role
        assert clinic["incidents"] == 1 and clinic["total"] == 2  # one problem, two failed attempts

        lessons = client.get(f"/api/agents/{impl['agent_id']}").json()["lessons"]
        assert lessons and lessons[0]["source"].startswith("task_run:") and lessons[0]["trust"] == "hypothesis"
        assert "(implement)" in lessons[0]["lesson"] and "Change the approach" in lessons[0]["lesson"]
        assert any(a["agent_id"] == impl["agent_id"] for a in client.get("/api/insights/lessons").json()["agents"])
        with transaction() as conn:  # not re-learned for the same run
            assert reliability.learn_from_mission(conn, mid) == 0


def test_lessons_reach_the_agents_next_prompt(monkeypatch):
    gw = FakeGateway(patch=EVIL)
    with live_client(monkeypatch, gw) as client:
        first = start(client)
        wait_for(lambda: mission_status(client, first)["status"] == "FAILED")
        gw.patch = FakeGateway().patch
        gw.calls = []
        second = start(client)
        pending_approval(client, second)
        prompts = [c.system for c in gw.calls]
        assert any("Lessons from your own earlier runs" in s and "[task_run:" in s for s in prompts)
        recalled = [e for e in client.get("/api/events?after=0").json()["events"] if e["event_type"] == "agent.lessons_recalled"]
        assert len(recalled) == 1  # announced once per attempt, not per model call


def test_completed_missions_get_an_objective_check(client):
    mid = start(client)
    a = pending_approval(client, mid)
    client.post(f"/api/approvals/{a['id']}/grant")
    wait_for(lambda: mission_status(client, mid)["status"] == "COMPLETED")
    obj = client.get(f"/api/missions/{mid}").json()["objective"]
    assert obj["met"] is True and obj["status"] == "objective_met" and obj["findings"]
    with transaction() as conn:  # a finished step that lacks a promised output fails the check
        t = conn.execute(select(db.tasks).where(db.tasks.c.mission_id == mid, db.tasks.c.key == "verify")).first()
        conn.execute(update(db.tasks).where(db.tasks.c.id == t.id).values(outputs={"passed": 5}))
        res = reliability.check_objective(conn, mid)
    assert res["met"] is False and "failed" in res["findings"][0]
    assert client.get(f"/api/missions/{mid}").json()["objective"]["met"] is False
    assert any(l["mode"] == "FM-3.1" for l in client.get("/api/insights/failures").json()["labels"])


def test_a_rejected_publish_is_partly_met_not_met(client):
    mid = start(client)
    a = pending_approval(client, mid)
    client.post(f"/api/approvals/{a['id']}/reject")
    wait_for(lambda: mission_status(client, mid)["status"] == "COMPLETED")
    obj = client.get(f"/api/missions/{mid}").json()["objective"]
    assert obj["status"] == "objective_partly_met" and "rejected" in obj["findings"][0]
    assert not [l for l in client.get("/api/insights/failures").json()["labels"] if l["mission_id"] == mid]  # your call, not a failure


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
    # a clear request still becomes a proposal, even a short one
    assert say(client, KADE, "fix the login bug")["proposal"]["kind"] == "create_mission"
    assert say(client, KADE, "fix the median function so even-length lists average the middle pair")["proposal"]["kind"] == "create_mission"


def test_mission_trace_orders_everything_with_totals(client):
    mid = start(client)
    a = pending_approval(client, mid)
    client.post(f"/api/approvals/{a['id']}/grant")
    wait_for(lambda: mission_status(client, mid)["status"] == "COMPLETED")
    tr = client.get(f"/api/insights/missions/{mid}/trace").json()
    kinds = {i["kind"] for i in tr["items"]}
    assert {"mission", "step", "tool", "message", "approval", "check"} <= kinds
    ats = [i["at"] for i in tr["items"]]
    assert ats == sorted(ats) and tr["items"][0]["title"].startswith("Mission created")
    assert tr["totals"]["tool_calls"] == len([i for i in tr["items"] if i["kind"] == "tool"]) > 0
    assert tr["totals"]["wall_ms"] is not None and tr["cost_is_estimate"] is True
    assert tr["by_agent"] and all(x["agent"] for x in tr["by_agent"])
    assert any(i["kind"] == "approval" and i["status"] != "PENDING" for i in tr["items"])  # the grant is on the timeline
    assert client.get("/api/insights/missions/00000000-0000-4000-8000-000000000999/trace").status_code == 404


def test_collaboration_network_comes_from_real_handoffs(client):
    assert client.get("/api/insights/collaboration").json()["edges"] == []
    mid = start(client)
    a = pending_approval(client, mid)
    client.post(f"/api/approvals/{a['id']}/grant")
    wait_for(lambda: mission_status(client, mid)["status"] == "COMPLETED")
    net = client.get("/api/insights/collaboration").json()
    assert net["method"] == "records" and net["edges"]
    top = net["edges"][0]
    assert top["handoffs"] >= 1 and top["weight"] >= 2 and top["a"] != top["b"]
    assert all(f["from"] != f["to"] for f in net["flows"])
    # the developer works with whoever handed them the reproduction and whoever verified their fix
    detail = client.get(f"/api/missions/{mid}").json()
    impl = next(t for t in detail["tasks"] if t["key"] == "implement")
    partners = net["partners"][impl["agent_id"]]
    assert partners and all(p["agent_id"] != impl["agent_id"] for p in partners)


def test_scorecards_count_finished_failed_and_first_try(monkeypatch):
    with live_client(monkeypatch, FakeGateway(patch=EVIL)) as client:
        bad = start(client)
        wait_for(lambda: mission_status(client, bad)["status"] == "FAILED")
        sc = client.get("/api/insights/scorecards").json()
        assert sc["method"] == "records" and len(sc["weeks"]) == 4 and sc["weeks"] == sorted(sc["weeks"])
        impl = next(t for t in client.get(f"/api/missions/{bad}").json()["tasks"] if t["key"] == "implement")
        dev = next(a for a in sc["agents"] if a["agent_id"] == impl["agent_id"])
        this = dev["weeks"][-1]
        assert this["failed"] == 1 and this["failed_runs"] == 2 and this["modes"] == {"FM-1.2": 2}
        assert dev["top_failure"] == "FM-1.2" and dev["trend"] == "not enough data"
        inspector = next(t for t in client.get(f"/api/missions/{bad}").json()["tasks"] if t["key"] == "inspect")
        arch = next(a for a in sc["agents"] if a["agent_id"] == inspector["agent_id"])
        assert arch["weeks"][-1]["finished"] >= 1 and arch["weeks"][-1]["first_try"] >= 1 and arch["total"]["first_try_rate"] == 1.0


def test_today_doesnt_hijack_other_requests(client):
    assert say(client, ATLAS, "What needs my approval today?")["reply"].startswith("Nothing is waiting")
    assert say(client, ATLAS, "what happened today?")["reply"].startswith("In the last day")
    assert say(client, ATLAS, "today?")["reply"].startswith("In the last day")
    assert say(client, ATLAS, "research a summary app on the App Store")["proposal"]["kind"] == "start_research"
