"""V6.43–V6.50: the owner's task list, quick capture, "do it for me", status that follows the run, review and redo,
today, repeating tasks, and the task list in the City chat."""
from datetime import datetime, timezone

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.management.capture import next_due, parse
from tests.integration.test_play import ATLAS
from tests.integration.test_schedules import _talk
from tests.integration.test_v619_v626 import _finished

LA = "America/Los_Angeles"
SUNDAY_1PM_LA = datetime(2026, 11, 1, 21, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- V6.44 quick capture

def test_capture_reads_a_task_the_way_you_say_it():
    t = parse("draft the Echo App Store blurb by Friday $1 urgent", LA, SUNDAY_1PM_LA)
    assert t["title"] == "Draft the Echo App Store blurb" and t["kind"] == "write" and t["priority"] == "urgent"
    assert t["budget_usd"] == 1.0 and t["due_at"] == "2026-11-07T01:00:00+00:00" and t["due_label"] == "Fri 5:00 PM"
    t = parse("fix the failing test in StackSprint tomorrow at 9am", LA, SUNDAY_1PM_LA)
    assert t["kind"] == "code" and t["due_label"] == "tomorrow 9:00 AM" and t["title"] == "Fix the failing test in StackSprint"
    assert parse("remind me to call mom tonight", LA, SUNDAY_1PM_LA)["title"] == "Call mom"
    assert parse("research budgeting apps every monday", LA, SUNDAY_1PM_LA)["repeat"] == "weekly"
    assert parse("pay rent nov 3", LA, SUNDAY_1PM_LA)["due_at"].startswith("2026-11-04T01:00")
    plain = parse("buy milk", LA, SUNDAY_1PM_LA)
    assert plain["due_at"] is None and plain["kind"] == "personal" and plain["budget_usd"] is None
    assert parse("buy a $90 jacket", LA, SUNDAY_1PM_LA)["budget_usd"] is None  # over the $50 cap: not a budget


def test_repeating_tasks_land_on_the_next_slot():
    fri = "2026-11-07T01:00:00+00:00"  # Friday 5pm in LA
    assert next_due(fri, "weekdays", LA, SUNDAY_1PM_LA) == "2026-11-10T01:00:00+00:00"  # Monday
    assert next_due(fri, "weekly", LA, SUNDAY_1PM_LA) == "2026-11-14T01:00:00+00:00"
    assert next_due(None, "none", LA) is None


# ---------------------------------------------------------------- V6.43 the list

def test_add_edit_finish_and_repeat(client):
    r = client.post("/api/my-tasks", json={"text": "write the weekly update every weekday at 9am", "tz": LA})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["repeat"] == "weekdays" and t["stage"] == "open" and t["kind"] == "write"
    assert client.post("/api/my-tasks", json={"title": "x"}).status_code == 422
    assert client.post("/api/my-tasks", json={}).status_code == 422
    e = client.patch(f"/api/my-tasks/{t['id']}", json={"priority": "urgent", "notes": "Keep it short"}).json()
    assert e["priority"] == "urgent" and e["notes"] == "Keep it short"
    assert client.patch(f"/api/my-tasks/{t['id']}", json={"clear_due": True}).json()["due_at"] is None
    done = client.post(f"/api/my-tasks/{t['id']}/done", json={"tz": LA}).json()
    assert done["task"]["stage"] == "done" and done["next"]["title"] == t["title"] and done["next"]["stage"] == "open"
    assert done["next"]["notes"] == "Keep it short"
    assert client.post(f"/api/my-tasks/{t['id']}/reopen").json()["stage"] == "open"
    assert client.post(f"/api/my-tasks/{t['id']}/drop").json()["stage"] == "dropped"
    assert client.delete(f"/api/my-tasks/{t['id']}").json() == {"ok": True}
    assert client.get(f"/api/my-tasks/{t['id']}").status_code == 404
    assert client.get("/api/my-tasks/not-a-uuid").status_code == 404
    preview = client.get("/api/my-tasks/parse", params={"text": "plan launch in 3 days", "tz": LA}).json()
    assert preview["title"] == "Plan launch" and preview["due_at"]
    assert client.get("/api/my-tasks").json()["tasks"][0]["title"] == t["title"]


def test_a_task_only_points_at_your_own_repository(client):
    r = client.post("/api/my-tasks", json={"title": "Fix it", "kind": "code", "repository_id": "00000000-0000-4000-8000-0000000000aa"})
    assert r.status_code == 404


# ---------------------------------------------------------------- V6.45–V6.47 do it, follow it, review it

def test_do_it_plans_does_and_comes_back_for_review(client):
    t = client.post("/api/my-tasks", json={"text": "draft the Echo App Store blurb $1", "tz": LA}).json()
    started = client.post(f"/api/my-tasks/{t['id']}/do")
    assert started.status_code == 200, started.text
    s = started.json()
    assert s["mission_id"] and s["stage"] == "working" and s["runs"] == 1
    assert client.post(f"/api/my-tasks/{t['id']}/do").status_code == 409  # already working on it
    m = _finished(client, s["mission_id"])
    assert m["status"] == "COMPLETED" and m["kind"] == "personal_task" and m["budget_usd"] == 1.0
    d = client.get(f"/api/my-tasks/{t['id']}").json()
    assert d["stage"] == "review"
    assert d["plan"]["content"].startswith("Simulation:") and "Settle the audience" in d["plan"]["content"]
    assert d["result"]["title"] == "Result: Draft the Echo App Store blurb" and "template" in d["result"]["content"]
    with db.get_engine().connect() as conn:  # the designer wrote it, at the Vision Quarter
        rows = conn.execute(select(db.tasks.c.key, db.agents.c.key).join(db.agents, db.agents.c.id == db.tasks.c.agent_id)
                            .where(db.tasks.c.mission_id == s["mission_id"])).all()
    assert sorted(rows) == [("task_do", "designer"), ("task_plan", "general_manager")]

    redo = client.post(f"/api/my-tasks/{t['id']}/redo", json={"note": "Make it punchier"}).json()
    assert redo["runs"] == 2 and redo["mission_id"] != s["mission_id"]
    detail = client.get(f"/api/missions/{redo['mission_id']}").json()
    assert detail["mission"]["params"]["redo_note"] == "Make it punchier"
    _finished(client, redo["mission_id"])
    assert client.post(f"/api/my-tasks/{t['id']}/done").json()["task"]["stage"] == "done"
    assert client.post(f"/api/my-tasks/{t['id']}/do").status_code == 409  # done: reopen first


def test_a_code_task_with_a_repository_runs_the_fix_mission(client):
    with db.get_engine().connect() as conn:
        repo = conn.execute(select(db.repositories.c.id)).scalar()
    t = client.post("/api/my-tasks", json={"title": "Fix the failing test in the sample project", "kind": "code",
                                           "repository_id": repo}).json()
    s = client.post(f"/api/my-tasks/{t['id']}/do").json()
    m = client.get(f"/api/missions/{s['mission_id']}").json()["mission"]
    assert m["kind"] == "fix_failing_test" and m["repository_id"] == repo


def test_do_it_holds_during_the_emergency_stop(client):
    t = client.post("/api/my-tasks", json={"title": "Research budgeting apps"}).json()
    with transaction() as conn:
        conn.execute(update(db.organizations).values(emergency_stopped=1))
    assert client.post(f"/api/my-tasks/{t['id']}/do").status_code == 409
    assert client.get(f"/api/my-tasks/{t['id']}").json()["runs"] == 0  # the claim was given back


# ---------------------------------------------------------------- V6.48 today

def test_today_lists_what_needs_you_first(client):
    client.post("/api/my-tasks", json={"text": "call the bank today at 11:59pm", "tz": "UTC"})
    client.post("/api/my-tasks", json={"title": "Old thing", "due_at": "2020-01-01T00:00:00Z"})
    t = client.get("/api/my-tasks/today?tz=UTC").json()
    assert len(t["overdue"]) == 1 and t["overdue"][0]["title"] == "Old thing" and t["next"]["title"] == "Old thing"
    assert "1 overdue" in t["spoken"] and t["open"] == 2


# ---------------------------------------------------------------- V6.50 the City chat

def test_add_list_and_do_tasks_from_the_city(client):
    r = _talk(client, ATLAS, "add a task: draft the Echo blurb by Friday")
    prop = r["proposal"]
    assert prop["kind"] == "add_task" and "Draft the Echo blurb" in prop["summary"]
    assert client.get("/api/my-tasks").json()["tasks"] == []  # nothing until you confirm
    ok = client.post(f"/api/play/proposals/{prop['id']}/confirm")
    assert ok.status_code == 200, ok.text
    assert client.get("/api/my-tasks").json()["tasks"][0]["title"] == "Draft the Echo blurb"
    assert "Next up: Draft the Echo blurb" in _talk(client, ATLAS, "what's on my list?")["reply"]
    do = _talk(client, ATLAS, "do the echo blurb task")["proposal"]
    assert do["kind"] == "do_task"
    res = client.post(f"/api/play/proposals/{do['id']}/confirm").json()
    assert res["status"] == "CONFIRMED" and "The team is on" in res["message"]["text"]
    _finished(client, res["result"]["mission_id"])
    assert "1 result to review" in _talk(client, ATLAS, "what's on my list?")["reply"]
    assert _talk(client, ATLAS, "remind me to stretch at 4pm")["proposal"]["kind"] == "add_task"


def test_the_weekly_report_counts_finished_tasks(client):
    t = client.post("/api/my-tasks", json={"title": "Pay the rent"}).json()
    client.post(f"/api/my-tasks/{t['id']}/done")
    r = client.get("/api/insights/weekly").json()
    assert r["tasks_done"] == 1 and "you finished 1 task from your list" in r["headline"]


# ---------------------------------------------------------------- review fixes

def test_capture_edge_cases():
    mon9 = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)   # Monday 9am in LA
    eve = datetime(2026, 11, 3, 2, 30, tzinfo=timezone.utc)    # Monday 6:30pm in LA
    fri9 = datetime(2026, 11, 6, 17, 0, tzinfo=timezone.utc)   # Friday 9am in LA
    assert parse("wrap up eow", LA, mon9)["due_label"] == "Fri 5:00 PM"
    assert parse("send invoice next week", LA, mon9)["due_at"] == "2026-11-10T01:00:00+00:00"  # next Monday, not Friday
    assert parse("call mom today", LA, eve)["due_label"] == "today 11:59 PM"  # never due in the past
    assert parse("gym every day", LA, eve)["due_label"] == "tomorrow 5:00 PM"
    assert parse("pay rent by friday", LA, fri9)["due_label"] == "today 5:00 PM"
    for words in ("decide 2 options for dinner", "buy sun screen", "review the market 5 picks"):
        t = parse(words, LA, mon9)
        assert t["due_at"] is None and t["title"].lower() == words, words
    assert parse("renew on feb 30", LA, mon9)["title"] == "Renew on feb 30"  # not a date: left as typed
    t = parse("fri nov 14 dentist", LA, mon9)
    assert t["title"] == "Dentist" and t["due_at"] == "2026-11-15T01:00:00+00:00"
    assert parse("call at 13pm", LA, mon9)["due_at"] is None


def test_finishing_twice_queues_one_repeat_and_drop_stops_the_run(client):
    t = client.post("/api/my-tasks", json={"text": "stretch every day", "tz": LA}).json()
    client.post(f"/api/my-tasks/{t['id']}/done")
    client.post(f"/api/my-tasks/{t['id']}/reopen")
    client.post(f"/api/my-tasks/{t['id']}/done")
    opens = [x for x in client.get("/api/my-tasks").json()["tasks"] if x["stage"] == "open"]
    assert len(opens) == 1
    w = client.post("/api/my-tasks", json={"title": "Research note-taking apps"}).json()
    run = client.post(f"/api/my-tasks/{w['id']}/do").json()["mission_id"]
    client.post(f"/api/my-tasks/{w['id']}/drop")
    assert _finished(client, run)["status"] in ("CANCELLED", "COMPLETED")
    assert client.get("/api/my-tasks/urn:uuid:" + w["id"]).status_code == 404


def test_a_second_press_while_starting_is_refused(client, monkeypatch):
    from services.management import mytasks
    t = client.post("/api/my-tasks", json={"title": "Write the launch post"}).json()
    seen = {}
    real = mytasks._start

    def slow(p, r, note):  # press again while the first press is still starting
        seen["second"] = client.post(f"/api/my-tasks/{t['id']}/do").status_code
        return real(p, r, note)

    monkeypatch.setattr(mytasks, "_start", slow)
    assert client.post(f"/api/my-tasks/{t['id']}/do").status_code == 200
    assert seen["second"] == 409
    with db.get_engine().connect() as conn:
        n = conn.execute(select(db.missions.c.id).where(db.missions.c.kind == "personal_task")).fetchall()
    assert len(n) == 1


def test_the_default_budget_follows_the_charter_cap(client):
    r = client.put("/api/charter", json={"mission_budget_cap_usd": 0.5, "note": "tight"})
    assert r.status_code == 200, r.text
    t = client.post("/api/my-tasks", json={"title": "Plan the week"}).json()
    s = client.post(f"/api/my-tasks/{t['id']}/do").json()
    assert client.get(f"/api/missions/{s['mission_id']}").json()["mission"]["budget_usd"] == 0.5
