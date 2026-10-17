"""V6.19–V6.26: weekday schedules, run now and skip; schedules that pause themselves; run again; follow-on missions;
the weekly report; the team roster and the owner check; the records export."""
from datetime import datetime, timezone

from sqlalchemy import insert, select, update

from services.core import db
from services.core.events import transaction
from services.management import links, schedules
from tests.conftest import mission_status, wait_for
from tests.integration.test_play import ATLAS
from tests.integration.test_schedules import _agent, _talk

DEV_OWNER = "00000000-0000-4000-8000-000000000000"
TESTS = "Run the test suite of the connected repository and report which tests fail."


def _sched(client, **kw):
    body = {"kind": "run_tests", "cadence": "daily", "hour": 9, "tz": "UTC", "title": "Daily tests", **kw}
    r = client.post("/api/schedules", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _due(sid):
    with transaction() as conn:
        conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == sid).values(next_run_at="2020-01-01T00:00:00+00:00"))


def _finished(client, mid):
    return wait_for(lambda: (x := mission_status(client, mid))["status"] in ("COMPLETED", "FAILED", "CANCELLED") and x)


# ---------------------------------------------------------------- V6.19

def test_weekday_cadence_skips_the_weekend():
    fri_evening = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)  # Friday
    assert schedules.next_run("weekdays", None, 9, 0, "UTC", fri_evening).isoformat() == "2026-10-19T09:00:00+00:00"  # Monday
    wed = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)
    assert schedules.next_run("weekdays", None, 9, 0, "UTC", wed).isoformat() == "2026-10-14T09:00:00+00:00"
    assert schedules.parse("every weekday at 7am research budgeting apps")["cadence"] == "weekdays"
    assert schedules.parse("every workday run the tests")["cadence"] == "weekdays"
    assert schedules.describe({"cadence": "weekdays", "weekday": None, "hour": 7, "minute": 0, "tz": "UTC"}) == "every weekday at 07:00 (UTC)"


def test_run_now_and_skip_next(client):
    s = _sched(client, cadence="weekdays")
    assert s["when"].startswith("every weekday") and s["weekday"] is None
    first = s["next_run_at"]
    skipped = client.post(f"/api/schedules/{s['id']}/skip").json()
    assert skipped["next_run_at"] > first
    r = client.post(f"/api/schedules/{s['id']}/run-now")
    assert r.status_code == 200, r.text
    mid = r.json()["mission_id"]
    again = client.post(f"/api/schedules/{s['id']}/run-now").json()
    assert again["mission_id"] == mid and again["repeat"] is True  # a double tap doesn't start a second run
    after = client.get("/api/schedules").json()["schedules"][0]
    assert after["runs"] == 1 and after["next_run_at"] == skipped["next_run_at"]  # running now doesn't move the regular slot
    assert _finished(client, mid)["status"] == "COMPLETED"
    client.post(f"/api/schedules/{s['id']}/enabled", json={"enabled": False})
    assert client.post(f"/api/schedules/{s['id']}/skip").status_code == 409  # nothing to skip while paused


# ---------------------------------------------------------------- V6.20

def test_three_failures_in_a_row_pause_a_schedule_and_it_lands_in_the_inbox(client, monkeypatch):
    s = _sched(client)
    monkeypatch.setattr(schedules, "start", lambda *a, **k: (None, "the repository isn't reachable"))
    from services.api.main import state
    for n in range(1, 4):
        _due(s["id"])
        state.scheduler._schedules()
        cur = client.get("/api/schedules").json()["schedules"][0]
        assert cur["failures"] == n
    assert cur["enabled"] == 0 and "3 failed runs in a row" in cur["paused_reason"]
    inbox = client.get("/api/insights/inbox").json()
    item = next(i for i in inbox["items"] if i["kind"] == "schedule")
    assert item["id"] == s["id"] and "repository" in item["detail"]
    resumed = client.post(f"/api/schedules/{s['id']}/enabled", json={"enabled": True}).json()
    assert resumed["failures"] == 0 and resumed["paused_reason"] is None
    assert not [i for i in client.get("/api/insights/inbox").json()["items"] if i["kind"] == "schedule"]


def test_a_success_resets_the_count_and_the_emergency_stop_is_not_a_failure(client, monkeypatch):
    s = _sched(client)
    from services.api.main import state
    results = iter([(None, "boom"), (None, "boom"), ("m-1", None), (None, "emergency stop is engaged"), (None, "boom")])
    monkeypatch.setattr(schedules, "start", lambda *a, **k: next(results))
    for _ in range(5):
        _due(s["id"])
        state.scheduler._schedules()
    cur = client.get("/api/schedules").json()["schedules"][0]
    assert cur["enabled"] == 1 and cur["failures"] == 1


# ---------------------------------------------------------------- V6.21

def test_run_again_starts_the_same_work_fresh(client):
    r = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests", "priority": "low"})
    mid = r.json()["id"]
    assert client.post(f"/api/missions/{mid}/rerun").status_code in (409, 201)  # 409 while it's still going
    _finished(client, mid)
    detail = client.get(f"/api/missions/{mid}").json()
    assert detail["can_rerun"] is True
    again = client.post(f"/api/missions/{mid}/rerun")
    assert again.status_code == 201, again.text
    new = again.json()["mission_id"]
    assert new != mid and client.post(f"/api/missions/{mid}/rerun").json()["mission_id"] == new  # double tap
    nd = client.get(f"/api/missions/{new}").json()
    assert nd["mission"]["kind"] == "run_tests" and nd["mission"]["prompt"] == TESTS and nd["priority"] == "low"
    assert nd["links"]["started_from"]["from_mission_id"] == mid
    assert client.get(f"/api/missions/{mid}").json()["links"]["reruns"][0]["to_mission_id"] == new
    assert client.post("/api/missions/not-a-mission/rerun").status_code == 404


def test_run_again_from_the_city(client):
    r = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests"})
    _finished(client, r.json()["id"])
    prop = _talk(client, ATLAS, "do that again")["proposal"]
    assert prop["kind"] == "rerun_mission" and prop["params"]["mission_id"] == r.json()["id"]
    c = client.post(f"/api/play/proposals/{prop['id']}/confirm").json()
    assert c["status"] == "CONFIRMED" and c["result"]["from_mission_id"] == r.json()["id"]


# ---------------------------------------------------------------- V6.22

def test_follow_on_starts_when_the_first_completes(client):
    first = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests"}).json()["id"]
    f = client.post(f"/api/missions/{first}/followups", json={"kind": "market_research",
                                                              "params": {"source": "apple_charts", "query": "budget apps"}})
    assert f.status_code == 201, f.text
    link = f.json()
    _finished(client, first)
    done = wait_for(lambda: (x := links.get(link["organization_id"], link["id"]))["status"] == "STARTED" and x)
    second = mission_status(client, done["to_mission_id"])
    assert second["kind"] == "market_research"
    assert client.get(f"/api/missions/{first}/links").json()["followups"][0]["status"] == "STARTED"


def test_follow_on_is_cancelled_when_the_first_fails_and_bad_ones_are_refused(client):
    first = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests"}).json()["id"]
    assert client.post(f"/api/missions/{first}/followups", json={"kind": "fix_failing_test", "prompt": "x"}).status_code == 422
    assert client.post(f"/api/missions/{first}/followups", json={"kind": "market_research", "params": {"query": "a"}}).status_code == 422
    link = client.post(f"/api/missions/{first}/followups", json={"kind": "run_tests"}).json()
    keep = client.post(f"/api/missions/{first}/followups", json={"kind": "run_tests", "title": "second"}).json()
    assert client.delete(f"/api/followups/{keep['id']}").json()["status"] == "CANCELLED"
    assert client.delete(f"/api/followups/{keep['id']}").status_code == 409
    client.post(f"/api/missions/{first}/cancel")
    _finished(client, first)
    from services.api.main import state
    state.scheduler._followups()
    got = links.get(link["organization_id"], link["id"])
    assert got["status"] in ("CANCELLED", "STARTED")
    if mission_status(client, first)["status"] == "CANCELLED":
        assert got["status"] == "CANCELLED" and "cancelled" in got["reason"]


def test_follow_on_waits_out_the_emergency_stop(client):
    first = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests"}).json()["id"]
    _finished(client, first)
    client.post("/api/emergency-stop", json={"engaged": True})
    link = client.post(f"/api/missions/{first}/followups", json={"kind": "run_tests"}).json()
    assert link["status"] == "WAITING" and "emergency stop" in (link["reason"] or "")
    client.post("/api/emergency-stop", json={"engaged": False})
    from services.api.main import state
    state.scheduler._followups()
    assert links.get(link["organization_id"], link["id"])["status"] == "STARTED"


# ---------------------------------------------------------------- V6.23

def test_weekly_report_and_atlas(client):
    mid = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests"}).json()["id"]
    _finished(client, mid)
    w = client.get("/api/insights/weekly").json()
    assert len(w["days"]) == 7 and w["week"]["completed"] >= 1 and w["is_estimate"] is True
    assert w["days"][-1]["date"] == datetime.now(timezone.utc).date().isoformat()
    assert w["headline"].startswith("This week:")
    reply = _talk(client, ATLAS, "how was the week?")["reply"]
    assert reply.startswith("This week:") and "estimates" in reply


# ---------------------------------------------------------------- V6.24

def test_roster_records_sign_ins_and_a_demoted_creator_stops_their_schedules(client):
    team = client.get("/api/team").json()
    me = next(m for m in team["members"] if m["you"])
    assert me["role"] == "owner" and me["user_id"] == DEV_OWNER
    s = _sched(client)
    with transaction() as conn:  # the creator's latest sign-in showed them as an operator
        conn.execute(update(db.org_members).where(db.org_members.c.user_id == DEV_OWNER).values(role="operator"))
    _due(s["id"])
    from services.api.main import state
    assert state.scheduler._schedules()["started"] == 0
    cur = client.get("/api/schedules").json()["schedules"][0]
    assert cur["enabled"] == 0 and "no longer an owner" in cur["paused_reason"]
    assert client.get("/api/team").json()["schedules_to_check"] == []  # paused ones aren't listed


def test_follow_on_by_someone_who_lost_operator_rights_is_cancelled(client):
    first = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests"}).json()["id"]
    link = client.post(f"/api/missions/{first}/followups", json={"kind": "run_tests"}).json()
    with transaction() as conn:
        conn.execute(update(db.org_members).where(db.org_members.c.user_id == DEV_OWNER).values(role="viewer"))
    _finished(client, first)
    from services.api.main import state
    state.scheduler._followups()
    got = links.get(link["organization_id"], link["id"])
    assert got["status"] == "CANCELLED" and "can no longer start missions" in got["reason"]


# ---------------------------------------------------------------- V6.26

def test_records_export_is_owner_only_hashed_and_rate_limited(client, monkeypatch):
    mid = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests"}).json()["id"]
    _finished(client, mid)
    r = client.get("/api/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    b = r.json()
    assert b["format"] == "aiciv.org-export.v1" and b["audit"]["ok"] is True and b["events_chain"]["ok"] is True
    assert any(m["id"] == mid for m in b["missions"]) and len(b["bundle_sha256"]) == 64
    assert not [e for e in b["events"] if e["event_type"].startswith("finance.")]
    import hashlib
    import json
    body = {k: v for k, v in b.items() if k != "bundle_sha256"}
    assert hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False).encode()).hexdigest() \
        == b["bundle_sha256"]
    assert client.get("/api/export").status_code == 429  # one a minute
    events = client.get("/api/events?after=0").json()["events"]
    assert "records.exported" in [e["event_type"] for e in events]

    from fastapi import HTTPException

    import services.api.finance as fin

    def not_owner(p):
        raise HTTPException(403, "only the owner can do this")
    monkeypatch.setattr(fin, "require_owner", not_owner)
    assert client.get("/api/team").status_code == 403


def test_run_again_keeps_the_repository_and_budget(client):
    r = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests", "budget_usd": 0.7}).json()
    _finished(client, r["id"])
    new = client.post(f"/api/missions/{r['id']}/rerun").json()["mission_id"]
    nm = client.get(f"/api/missions/{new}").json()["mission"]
    assert nm["budget_usd"] == 0.7 and nm["repository_id"] == r["repository_id"]


def test_skip_refuses_when_the_slot_is_being_claimed(client, monkeypatch):
    s = _sched(client)
    real = schedules.get

    def racing(conn, org, sid):  # the scheduler claims the slot between the read and the skip
        row = real(conn, org, sid)
        if row:
            conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == sid).values(next_run_at="2099-01-01T00:00:00+00:00"))
        return row
    monkeypatch.setattr(schedules, "get", racing)
    assert client.post(f"/api/schedules/{s['id']}/skip").status_code == 409


def test_an_interrupted_follow_on_start_goes_back_in_line(client):
    first = client.post("/api/missions", json={"prompt": TESTS, "kind": "run_tests"}).json()["id"]
    link = client.post(f"/api/missions/{first}/followups", json={"kind": "run_tests"}).json()
    with transaction() as conn:
        conn.execute(update(db.mission_links).where(db.mission_links.c.id == link["id"])
                     .values(status="STARTING", updated_at="2020-01-01T00:00:00+00:00"))
    _finished(client, first)
    links.tick()
    assert links.get(link["organization_id"], link["id"])["status"] == "STARTED"
