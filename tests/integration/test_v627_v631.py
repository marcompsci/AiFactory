"""V6.27–V6.31: the weekly report in your time zone; schedules pause when their creator hasn't signed in for 30 days;
saved requests; schedule costs and per-run budgets; comparing runs."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, update

from services.core import db
from services.core.events import transaction
from services.management import schedules, weekly
from tests.conftest import mission_status, wait_for
from tests.integration.test_play import ATLAS
from tests.integration.test_schedules import _agent, _talk
from tests.integration.test_v619_v626 import DEV_OWNER, TESTS, _due, _finished, _sched


# ---------------------------------------------------------------- V6.27

def test_weekly_days_follow_your_time_zone(client):
    with db.get_engine().connect() as conn:
        # 03:00 UTC on Oct 17 is still Oct 16 in Los Angeles
        now = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
        la = weekly.report(conn, "0b3a6f1e-6c1d-4b8e-9f0a-1a2b3c4d5e60", now=now, tz="America/Los_Angeles")
        utc = weekly.report(conn, "0b3a6f1e-6c1d-4b8e-9f0a-1a2b3c4d5e60", now=now, tz="UTC")
        bad = weekly.report(conn, "0b3a6f1e-6c1d-4b8e-9f0a-1a2b3c4d5e60", now=now, tz="Mars/Base")
    assert la["days"][-1]["date"] == "2026-10-16" and utc["days"][-1]["date"] == "2026-10-17"
    assert la["from"].startswith("2026-10-10T07:00") and la["tz"] == "America/Los_Angeles" and bad["tz"] == "UTC"
    mid = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests"}).json()["id"]
    _finished(client, mid)
    r = client.get("/api/insights/weekly?tz=Asia/Tokyo").json()
    assert r["tz"] == "Asia/Tokyo" and r["week"]["completed"] >= 1


# ---------------------------------------------------------------- V6.28

def test_a_creator_who_has_not_signed_in_for_30_days_pauses_the_schedule(client):
    s = _sched(client)
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    with transaction() as conn:
        conn.execute(update(db.org_members).where(db.org_members.c.user_id == DEV_OWNER).values(last_seen=old))
    from services.core import roster
    roster.clear()  # (the next request would refresh last_seen; the scheduler runs without one)
    _due(s["id"])
    from services.api.main import state
    assert state.scheduler._schedules()["started"] == 0
    with db.get_engine().connect() as conn:
        cur = schedules.get(conn, s["organization_id"], s["id"])
    assert cur["enabled"] == 0 and "hasn't signed in for 30 days" in cur["paused_reason"]


def test_an_old_schedule_from_someone_never_seen_pauses_but_a_new_one_runs(client):
    with transaction() as conn:
        org = "0b3a6f1e-6c1d-4b8e-9f0a-1a2b3c4d5e60"
        stranger = "00000000-0000-4000-8000-0000000000ff"
        new = {"organization_id": org, "created_by": stranger, "created_at": datetime.now(timezone.utc).isoformat()}
        old = {**new, "created_at": (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()}
        assert schedules.owner_problem(conn, new) is None
        assert "can't be confirmed" in schedules.owner_problem(conn, old)


# ---------------------------------------------------------------- V6.29

def test_saved_requests_start_from_the_api_and_the_city(client):
    r = client.post("/api/saved-requests", json={"name": "Nightly tests", "kind": "run_tests", "priority": "low"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post("/api/saved-requests", json={"name": "nightly  TESTS", "kind": "run_tests"}).status_code == 409
    assert client.post("/api/saved-requests", json={"name": "Bad", "kind": "fix_failing_test", "prompt": "x"}).status_code == 422
    start = client.post(f"/api/saved-requests/{sid}/start")
    assert start.status_code == 201, start.text
    mid = start.json()["mission_id"]
    assert client.post(f"/api/saved-requests/{sid}/start").json() == {"mission_id": mid, "saved_request_id": sid, "repeat": True}
    detail = client.get(f"/api/missions/{mid}").json()
    assert detail["mission"]["kind"] == "run_tests" and detail["priority"] == "low"
    _finished(client, mid)
    listed = client.get("/api/saved-requests").json()["saved_requests"][0]
    assert listed["uses"] == 1 and listed["last_mission_id"] == mid

    prop = _talk(client, ATLAS, "start nightly tests")["proposal"]
    assert prop["kind"] == "start_saved" and prop["params"]["saved_request_id"] == sid
    with transaction() as conn:  # past the double-tap window
        conn.execute(update(db.saved_requests).where(db.saved_requests.c.id == sid).values(last_used_at="2020-01-01T00:00:00+00:00"))
    c = client.post(f"/api/play/proposals/{prop['id']}/confirm").json()
    assert c["status"] == "CONFIRMED" and c["result"]["mission_id"] != mid
    assert _talk(client, ATLAS, "start something nobody saved")["proposal"] is None or \
        _talk(client, ATLAS, "start something nobody saved")["proposal"]["kind"] != "start_saved"
    from services.core import auth
    auth.mutation_limiter._state.clear()  # this test makes more changes than the burst allows
    assert client.delete(f"/api/saved-requests/{sid}").json() == {"ok": True}
    assert client.post(f"/api/saved-requests/{sid}/start").status_code == 404
    assert client.post("/api/saved-requests/not-an-id/start").status_code == 404


def test_save_a_finished_mission_keeps_its_repository_and_budget(client):
    r = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests", "budget_usd": 0.6}).json()
    _finished(client, r["id"])
    s = client.post(f"/api/missions/{r['id']}/save", json={"name": "Cheap tests"})
    assert s.status_code == 201, s.text
    spec = s.json()["spec"]
    assert spec["budget_usd"] == 0.6 and spec["repository_id"] == r["repository_id"]
    mid = client.post(f"/api/saved-requests/{s.json()['id']}/start").json()["mission_id"]
    assert client.get(f"/api/missions/{mid}").json()["mission"]["budget_usd"] == 0.6


def test_a_mission_cannot_name_another_organizations_repository(client):
    r = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests", "repository_id": "00000000-0000-4000-8000-0000000000ee"})
    assert r.status_code == 404


# ---------------------------------------------------------------- V6.30

def test_schedule_costs_and_budget(client):
    s = _sched(client)
    assert s["cost"]["runs_counted"] == 0 and s["budget_usd"] is None
    assert client.post(f"/api/schedules/{s['id']}/budget", json={"budget_usd": 0.4}).json()["budget_usd"] == 0.4
    mid = client.post(f"/api/schedules/{s['id']}/run-now").json()["mission_id"]
    _finished(client, mid)
    assert client.get(f"/api/missions/{mid}").json()["mission"]["budget_usd"] == 0.4
    cur = client.get("/api/schedules").json()["schedules"][0]
    assert cur["cost"]["runs_counted"] == 1 and cur["cost"]["is_estimate"] is True and cur["cost"]["per_run_usd"] is not None
    assert client.put("/api/charter", json={"mission_budget_cap_usd": 0.3, "note": "tighter"}).status_code == 200
    assert client.post(f"/api/schedules/{s['id']}/budget", json={"budget_usd": 0.4}).status_code == 422
    assert client.post(f"/api/schedules/{s['id']}/budget", json={"budget_usd": None}).json()["budget_usd"] is None


def test_research_runs_take_the_budget():
    from services.api.v4 import ResearchIn
    assert ResearchIn(source="etsy", query="candles", budget_usd=0.5).budget_usd == 0.5


# ---------------------------------------------------------------- V6.31

def test_compare_a_rerun_with_the_original(client):
    first = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests"}).json()["id"]
    _finished(client, first)
    second = client.post(f"/api/missions/{first}/rerun").json()["mission_id"]
    _finished(client, second)
    c = client.get(f"/api/missions/{second}/compare").json()
    assert c["before"]["id"] == first and c["how"] == "started again from" and c["changes"]
    assert c["this"]["steps"]["total"] >= 1
    alone = client.get(f"/api/missions/{first}/compare").json()
    assert alone["before"] is None
    assert client.get(f"/api/missions/{first}/compare?with_id={second}").json()["before"]["id"] == second
    assert client.get(f"/api/missions/{first}/compare?with_id=nope").status_code == 404


def test_compare_a_schedule_run_with_the_previous_one(client):
    s = _sched(client)
    a = client.post(f"/api/schedules/{s['id']}/run-now").json()["mission_id"]
    _finished(client, a)
    with transaction() as conn:
        conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == s["id"]).values(last_run_at="2020-01-01T00:00:00+00:00"))
    b = client.post(f"/api/schedules/{s['id']}/run-now").json()["mission_id"]
    _finished(client, b)
    c = client.get(f"/api/missions/{b}/compare").json()
    assert c["before"]["id"] == a and c["how"] == "the schedule's previous run"


def test_review_fixes_saved_research_budget_compare_self_and_bad_repo_ids(client):
    r = client.post("/api/saved-requests", json={"name": "Candles", "kind": "market_research",
                                                 "params": {"source": "etsy", "query": "candles"}, "budget_usd": 0.5})
    assert r.status_code == 201, r.text
    mid = client.post(f"/api/saved-requests/{r.json()['id']}/start").json()["mission_id"]
    assert client.get(f"/api/missions/{mid}").json()["mission"]["budget_usd"] == 0.5
    assert client.get(f"/api/missions/{mid}/compare?with_id={mid}").status_code == 422
    assert client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests", "repository_id": "nope"}).status_code == 404


def test_saved_request_claim_refuses_a_second_start_while_starting(client, monkeypatch):
    sid = client.post("/api/saved-requests", json={"name": "Again", "kind": "run_tests"}).json()["id"]
    from services.management import saved
    with transaction() as conn:  # mid-start: claimed a moment ago, no mission yet
        conn.execute(update(db.saved_requests).where(db.saved_requests.c.id == sid)
                     .values(last_used_at=datetime.now(timezone.utc).isoformat(), last_mission_id=None))
    assert client.post(f"/api/saved-requests/{sid}/start").status_code == 409

    def boom(*a, **k):
        raise RuntimeError("worker unavailable")
    with transaction() as conn:
        conn.execute(update(db.saved_requests).where(db.saved_requests.c.id == sid).values(last_used_at=None))
    monkeypatch.setattr(saved.links, "start", boom)
    assert client.post(f"/api/saved-requests/{sid}/start").status_code == 422
    with db.get_engine().connect() as conn:  # the claim was put back, so it can be tried again at once
        assert saved._row(conn, client.get("/api/saved-requests").json()["saved_requests"][0]["organization_id"], sid).last_used_at is None
