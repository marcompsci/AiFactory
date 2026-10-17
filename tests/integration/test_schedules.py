"""V6.16 scheduled missions: a schedule exists only after the owner confirms it; due runs start the regular way (the
emergency stop and charter apply), each slot runs once, and the owner can pause, resume or delete it."""
from datetime import datetime, timezone

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.management import charter, schedules
from tests.conftest import mission_status, wait_for
from tests.integration.test_play import ATLAS, say


def _agent(client, key):
    return next(a["id"] for a in client.get("/api/snapshot").json()["agents"] if a["key"] == key)


def _talk(client, agent, text, tz="America/Los_Angeles"):
    r = client.post("/api/play/talk", json={"agent_id": agent, "text": text, "tz": tz})
    assert r.status_code == 200, r.text
    return r.json()


def test_reading_every_day_and_every_monday():
    assert schedules.parse("every monday at 9am run the tests") == {"cadence": "weekly", "weekday": 0, "hour": 9, "minute": 0, "rest": "run the tests"}
    assert schedules.parse("every day at 6:30 pm research budgeting apps")["hour"] == 18
    assert schedules.parse("every day research candles on etsy")["hour"] == 9  # 9:00 when no time is given
    assert schedules.parse("run the tests") is None
    after = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)  # Friday 13:00 in Los Angeles
    nxt = schedules.next_run("weekly", 0, 9, 0, "America/Los_Angeles", after)
    assert nxt.isoformat() == "2026-10-19T16:00:00+00:00"  # Monday 09:00 PDT
    assert schedules.next_run("daily", None, 9, 0, "UTC", after).isoformat() == "2026-10-17T09:00:00+00:00"


def test_a_schedule_needs_your_confirm_then_runs_once_per_slot(client):
    sentry = _agent(client, "qa")
    r = _talk(client, sentry, "every monday at 9 run the tests")
    prop = r["proposal"]
    assert prop["kind"] == "create_schedule" and "Monday at 09:00 (America/Los_Angeles)" in prop["summary"]
    assert client.get("/api/schedules").json()["schedules"] == []  # nothing until you confirm
    c = client.post(f"/api/play/proposals/{prop['id']}/confirm")
    assert c.status_code == 200, c.text
    sid = c.json()["result"]["schedule_id"]
    s = client.get("/api/schedules").json()["schedules"][0]
    assert s["id"] == sid and s["kind"] == "run_tests" and s["enabled"] == 1 and s["runs"] == 0

    with transaction() as conn:  # make it due now
        conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == sid).values(next_run_at="2020-01-01T00:00:00+00:00"))
    from services.api.main import state
    assert state.scheduler._schedules() == {"due": 1, "started": 1}
    assert state.scheduler._schedules() == {"due": 0, "started": 0}  # the slot was claimed: no second run
    s = client.get("/api/schedules").json()["schedules"][0]
    assert s["runs"] == 1 and s["last_error"] is None and s["next_run_at"] > datetime.now(timezone.utc).isoformat()
    m = wait_for(lambda: (x := mission_status(client, s["last_mission_id"]))["status"] in ("COMPLETED", "FAILED") and x)
    assert m["status"] == "COMPLETED" and m["kind"] == "run_tests"
    assert "schedule.ran" in [e["event_type"] for e in client.get("/api/events?after=0").json()["events"]]


def test_research_schedules_and_who_may_set_them(client):
    lumen = _agent(client, "researcher")
    prop = _talk(client, lumen, "every day at 7am research budgeting apps on the App Store")["proposal"]
    assert prop["params"]["kind"] == "market_research" and prop["params"]["params"]["query"] == "budgeting apps"
    kade = _agent(client, "developer")
    assert _talk(client, kade, "every day run the tests")["proposal"] is None
    wk = _talk(client, sentry := _agent(client, "qa"), "every weekday at 8:15 run the tests")["proposal"]
    assert wk["params"]["cadence"] == "weekdays" and "every weekday at 08:15" in wk["summary"]
    assert _talk(client, sentry, "every day dance")["proposal"] is None
    # a time zone the server doesn't know falls back to UTC rather than failing
    assert "(UTC)" in _talk(client, ATLAS, "every day at 8 run the tests", tz="Mars/Base")["proposal"]["summary"]


def test_emergency_stop_and_quiet_hours_hold_schedules_and_the_owner_controls_them(client):
    r = client.post("/api/schedules", json={"kind": "run_tests", "cadence": "daily", "hour": 9, "tz": "UTC", "title": "Daily tests"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    client.post("/api/emergency-stop", json={"engaged": True})
    with transaction() as conn:
        conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == sid).values(next_run_at="2020-01-01T00:00:00+00:00"))
    from services.api.main import state
    assert state.scheduler._schedules()["started"] == 0
    s = client.get("/api/schedules").json()["schedules"][0]
    assert "emergency stop" in s["last_error"] and s["runs"] == 0
    client.post("/api/emergency-stop", json={"engaged": False})
    assert "schedules" in charter.QUIET_JOBS  # quiet hours hold schedules like other scheduled work
    # pause, resume (never back-fills), delete
    assert client.post(f"/api/schedules/{sid}/enabled", json={"enabled": False}).json()["enabled"] == 0
    with transaction() as conn:
        conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == sid).values(next_run_at="2020-01-01T00:00:00+00:00"))
    assert state.scheduler._schedules()["due"] == 0  # paused schedules don't run
    resumed = client.post(f"/api/schedules/{sid}/enabled", json={"enabled": True}).json()
    assert resumed["enabled"] == 1 and resumed["next_run_at"] > datetime.now(timezone.utc).isoformat()
    assert client.delete(f"/api/schedules/{sid}").status_code == 200
    assert client.get("/api/schedules").json()["schedules"] == []
    assert client.post("/api/schedules", json={"kind": "fix_failing_test", "cadence": "daily", "hour": 9, "title": "nope"}).status_code == 422
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.mission_schedules)).first() is None


def test_only_the_owner_schedules_and_bad_times_are_refused_up_front(client, monkeypatch):
    sentry = _agent(client, "qa")
    assert _talk(client, sentry, "every day at 25 run the tests")["reply"].startswith("I can't schedule that")
    assert _talk(client, sentry, "check the test results")["proposal"] is None or \
        _talk(client, sentry, "check the test results")["proposal"]["params"].get("kind") != "run_tests"
    assert _talk(client, sentry, "run the tests and fix the failing one")["proposal"] is None or \
        _talk(client, sentry, "run the tests and fix the failing one")["proposal"]["params"].get("kind") != "run_tests"
    prop = _talk(client, sentry, "every day at 9 run the tests")["proposal"]
    from fastapi import HTTPException

    def not_owner(p):
        raise HTTPException(403, "requires role owner")
    import services.finance.permissions as perms
    monkeypatch.setattr(perms, "require_owner", not_owner)
    r = client.post(f"/api/play/proposals/{prop['id']}/confirm").json()
    assert r["status"] == "FAILED" and client.get("/api/schedules").json()["schedules"] == []
