"""V6.5 recovery plans: a failed mission gets a plan matched to its failure, it runs only on the owner's approval, the
new mission carries the lesson, and recoveries stop after two in a row."""
from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.management import recovery
from tests.conftest import mission_status, wait_for
from tests.integration.test_missions import FakeGateway, live_client, start
from tests.integration.test_reliability import EVIL


def _plan(client, mid):
    return wait_for(lambda: next(iter(client.get(f"/api/missions/{mid}").json()["recovery"]), None))


def test_a_role_violation_gets_a_guided_retry_that_waits_for_you(monkeypatch):
    with live_client(monkeypatch, FakeGateway(patch=EVIL)) as client:
        mid = start(client)
        wait_for(lambda: mission_status(client, mid)["status"] == "FAILED")
        plan = _plan(client, mid)
        assert plan["status"] == "PENDING" and plan["strategy"] == "retry_with_guidance" and plan["failure_mode"] == "FM-1.2"
        assert "never edit the tests" in plan["summary"] and plan["actionable"]
        prompt = plan["params"]["prompt"]
        assert "Do not modify any test file" in prompt and "Lesson:" in prompt and "refusing to edit tests" in prompt
        # nothing has started on its own
        assert len(client.get("/api/missions").json()["missions"]) == 1
        assert "recovery.proposed" in [e["event_type"] for e in client.get("/api/events?after=0").json()["events"]]

        r = client.post(f"/api/recovery/{plan['id']}/approve")
        assert r.status_code == 200, r.text
        new = r.json()["mission"]
        assert new["title"].startswith("Recovery:") and "Recovery notes" in new["prompt"]
        assert client.post(f"/api/recovery/{plan['id']}/approve").status_code == 409  # once only
        assert client.get("/api/recovery").json()["plans"][0]["new_mission_id"] == new["id"]


def test_an_outage_gets_a_plain_retry_and_can_be_declined(monkeypatch):
    with live_client(monkeypatch, FakeGateway(fail=True)) as client:
        mid = start(client)
        wait_for(lambda: mission_status(client, mid)["status"] == "FAILED")
        plan = _plan(client, mid)
        assert plan["strategy"] == "retry_later" and plan["failure_mode"] == "INFRA"
        assert "Recovery notes" not in plan["params"]["prompt"]  # nothing to fix in the plan itself
        assert client.post(f"/api/recovery/{plan['id']}/decline").json()["plan"]["status"] == "DECLINED"
        assert client.post(f"/api/recovery/{plan['id']}/approve").status_code == 409
        assert len(client.get("/api/missions").json()["missions"]) == 1


def test_recoveries_stop_after_two_in_a_row(monkeypatch):
    with live_client(monkeypatch, FakeGateway(patch=EVIL)) as client:
        mid = start(client)
        for depth in (1, 2):
            wait_for(lambda: mission_status(client, mid)["status"] == "FAILED")
            plan = _plan(client, mid)
            assert plan["params"]["recovery_depth"] == depth and plan["actionable"]
            mid = client.post(f"/api/recovery/{plan['id']}/approve").json()["mission"]["id"]
        wait_for(lambda: mission_status(client, mid)["status"] == "FAILED")
        third = _plan(client, mid)
        assert third["strategy"] == "none" and third["status"] == "INFO" and not third["actionable"]
        assert client.post(f"/api/recovery/{third['id']}/approve").status_code == 409


def test_plans_lapse_after_a_week_and_only_failed_fix_missions_get_one(client):
    mid = start(client)
    wait_for(lambda: mission_status(client, mid)["status"] == "WAITING_FOR_APPROVAL")
    with transaction() as conn:
        assert recovery.propose(conn, mid) is None  # not failed
    with transaction() as conn:
        conn.execute(db.recovery_plans.insert().values(id=db.new_id(), organization_id=conn.execute(select(db.missions.c.organization_id)
                     .where(db.missions.c.id == mid)).scalar(), mission_id=mid, failure_mode="INFRA", strategy="retry_later",
                     summary="s", rationale="r", params={"prompt": "x" * 20}, status="PENDING", created_at="2020-01-01T00:00:00+00:00"))
        assert recovery.expire(conn) == 1
        assert conn.execute(select(db.recovery_plans.c.status).where(db.recovery_plans.c.mission_id == mid)).scalar() == "EXPIRED"


def test_a_plan_that_cannot_start_goes_back_to_waiting_and_decided_plans_stay_decided(monkeypatch):
    with live_client(monkeypatch, FakeGateway(fail=True)) as client:
        mid = start(client)
        wait_for(lambda: mission_status(client, mid)["status"] == "FAILED")
        plan = _plan(client, mid)
        client.post("/api/emergency-stop", json={"engaged": True})
        assert client.post(f"/api/recovery/{plan['id']}/approve").status_code == 409  # emergency stop refuses the mission
        again = client.get(f"/api/missions/{mid}").json()["recovery"][0]
        assert again["status"] == "PENDING" and again["new_mission_id"] is None  # nothing started, still your call
        client.post("/api/emergency-stop", json={"engaged": False})
        with transaction() as conn:  # only one decision can win
            assert recovery.claim(conn, plan["id"], user_id="00000000-0000-4000-8000-000000000000", approve=False) is True
            assert recovery.claim(conn, plan["id"], user_id="00000000-0000-4000-8000-000000000000", approve=True) is False
        assert client.post(f"/api/recovery/{plan['id']}/approve").status_code == 409
        assert len(client.get("/api/missions").json()["missions"]) == 1
