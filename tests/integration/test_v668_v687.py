"""V6.68–V6.87: checklists, lists, estimates, snooze, waiting-on, templates, plan my day, focus, the weekly review,
estimates before a run, feedback on results, the results library and productivity insights."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.management import taskplus
from services.management.capture import parse
from tests.integration.test_v619_v626 import _finished

LA = "America/Los_Angeles"


def _add(client, text, **kw):
    r = client.post("/api/my-tasks", json={"text": text, "tz": LA, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_capture_reads_lists_and_estimates():
    t = parse("draft the Echo blurb 45m #echo $1", LA)
    assert t["title"] == "Draft the Echo blurb" and t["list_name"] == "echo" and t["estimate_minutes"] == 45
    assert parse("gym 1.5h #health", LA)["estimate_minutes"] == 90
    assert parse("write 3 posts", LA)["estimate_minutes"] is None
    assert parse("nap 2m", LA)["estimate_minutes"] is None  # under 5 minutes isn't an estimate
    # lengths that aren't estimates stay in the title
    assert parse("Buy 2 m of rope", LA)["title"] == "Buy 2 m of rope"
    assert parse("Return book within 24h", LA)["title"] == "Return book within 24h"
    r = parse("Run 100m sprint drills", LA)
    assert r["title"] == "Run 100m sprint drills" and r["estimate_minutes"] is None
    assert parse("walk for 20 m", LA)["estimate_minutes"] == 20


def test_checklists_lists_and_estimates(client):
    t = _add(client, "plan the launch 2h #echo", items=["Pick a date", "Write the post"])
    assert t["list_name"] == "echo" and t["estimate_minutes"] == 120 and t["items_total"] == 2
    d = client.get(f"/api/my-tasks/{t['id']}").json()
    first = d["items"][0]
    assert [i["text"] for i in d["items"]] == ["Pick a date", "Write the post"]
    items = client.patch(f"/api/my-tasks/{t['id']}/items/{first['id']}", json={"done": True}).json()["items"]
    assert items[0]["done"] is True
    items = client.post(f"/api/my-tasks/{t['id']}/items", json={"texts": ["Tell the team"]}).json()["items"]
    assert len(items) == 3
    assert client.delete(f"/api/my-tasks/{t['id']}/items/{items[2]['id']}").json()["items"][-1]["text"] == "Write the post"
    assert client.patch(f"/api/my-tasks/{t['id']}/items/not-an-id", json={"done": True}).status_code == 404
    e = client.patch(f"/api/my-tasks/{t['id']}", json={"list_name": "#Home", "estimate_minutes": 30}).json()
    assert e["list_name"] == "home" and e["estimate_minutes"] == 30
    assert client.patch(f"/api/my-tasks/{t['id']}", json={"list_name": "bad name!"}).status_code == 422
    listed = client.get("/api/my-tasks").json()["tasks"][0]
    assert listed["items_done"] == 1 and listed["items_total"] == 2


def test_repeats_keep_their_list_estimate_and_checklist(client):
    t = _add(client, "weekly review every monday 30m #home", items=["Inbox zero"])
    client.patch(f"/api/my-tasks/{t['id']}/items/{client.get(f'/api/my-tasks/{t[chr(105) + chr(100)]}').json()['items'][0]['id']}",
                 json={"done": True})
    nxt = client.post(f"/api/my-tasks/{t['id']}/done", json={"tz": LA}).json()["next"]
    assert nxt["list_name"] == "home" and nxt["estimate_minutes"] == 30 and nxt["items_total"] == 1 and nxt["items_done"] == 0


def test_snooze_and_waiting_on(client):
    a = _add(client, "buy paint")
    b = _add(client, "paint the fence")
    s = client.post(f"/api/my-tasks/{a['id']}/snooze", json={"preset": "tomorrow", "tz": LA}).json()
    assert s["stage"] == "snoozed" and s["snoozed_until"]
    assert client.post(f"/api/my-tasks/{a['id']}/snooze", json={"preset": "wake"}).json()["stage"] == "open"
    w = client.patch(f"/api/my-tasks/{b['id']}", json={"blocked_by": a["id"]}).json()
    assert w["stage"] == "blocked" and w["blocked_by_title"] == "Buy paint"
    assert client.patch(f"/api/my-tasks/{a['id']}", json={"blocked_by": b["id"]}).status_code == 422  # no loops
    assert client.patch(f"/api/my-tasks/{a['id']}", json={"blocked_by": a["id"]}).status_code == 422
    client.post(f"/api/my-tasks/{a['id']}/done")
    assert client.get(f"/api/my-tasks/{b['id']}").json()["stage"] == "open"  # what it waited on is done
    client.delete(f"/api/my-tasks/{a['id']}")
    assert client.get(f"/api/my-tasks/{b['id']}").json()["blocked_by"] is None


def test_templates(client):
    t = _add(client, "publish an episode 1h #pod", items=["Edit", "Upload", "Post"])
    tmpl = client.post(f"/api/my-tasks/{t['id']}/template", json={"name": "Episode"}).json()
    assert tmpl["name"] == "Episode" and tmpl["items"] == ["Edit", "Upload", "Post"]
    assert client.get("/api/my-tasks/templates").json()["templates"][0]["id"] == tmpl["id"]
    new = client.post(f"/api/my-tasks/templates/{tmpl['id']}/use", json={}).json()
    assert new["title"] == "Publish an episode" and new["items_total"] == 3 and new["list_name"] == "pod"
    assert client.delete(f"/api/my-tasks/templates/{tmpl['id']}").json() == {"ok": True}
    assert client.post(f"/api/my-tasks/templates/{tmpl['id']}/use").status_code == 404


def test_plan_my_day_orders_and_sizes_the_day(client):
    _add(client, "answer email 30m")
    _add(client, "old thing", due_at="2020-01-01T00:00:00Z")
    _add(client, "write the report 90m urgent")
    assert client.get("/api/my-tasks/plan", params={"tz": "UTC"}).status_code == 200
    with db.get_engine().connect() as conn:  # at a fixed time of day, so the whole day is still ahead
        org = conn.execute(select(db.my_tasks.c.organization_id)).scalar()
        p = taskplus.plan_day(conn, org, "UTC", "09:00", "18:00", now=datetime.now(timezone.utc).replace(hour=8, minute=0))
    titles = [b["title"] for b in p["blocks"]]
    assert titles[0] == "Old thing" and titles[1] == "Write the report"  # overdue first, then urgent
    assert p["blocks"][1]["minutes"] == 90 and p["blocks"][0]["estimated"] is True
    assert client.get("/api/my-tasks/plan", params={"start": "18:00", "end": "09:00"}).status_code == 422


def test_plan_lists_what_does_not_fit(client):
    now = datetime(2026, 11, 12, 16, 0, tzinfo=timezone.utc)
    with db.get_engine().connect() as conn:
        p = taskplus.plan_day(conn, "00000000-0000-4000-8000-0000000000ff", "UTC", "16:00", "16:10", now=now)
    assert p["blocks"] == [] and p["free_minutes"] == 10


def test_focus_and_insights(client):
    t = _add(client, "write the newsletter")
    f = client.post(f"/api/my-tasks/{t['id']}/focus", json={"minutes": 25}).json()
    assert f["task_total_minutes"] == 25
    assert client.post(f"/api/my-tasks/{t['id']}/focus", json={"minutes": 500}).status_code == 422
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    assert client.post(f"/api/my-tasks/{t['id']}/focus", json={"minutes": 10, "started_at": future}).status_code == 422
    client.post(f"/api/my-tasks/{t['id']}/done")
    i = client.get("/api/insights/tasks", params={"tz": "UTC"}).json()
    assert i["done"] == 1 and i["focus_minutes"] == 25 and i["added"] == 1 and len(i["series"]) == 14
    assert i["series"][-1]["done"] == 1 and "1 done in 14 days" in i["headline"]


def test_estimate_feedback_library_and_quality(client):
    t = _add(client, "draft the launch email")
    e = client.get(f"/api/my-tasks/{t['id']}/estimate").json()
    assert e["label"] == "estimate" and e["runs"] == 0 and e["cost_usd"] is None
    assert client.post(f"/api/my-tasks/{t['id']}/feedback", json={"rating": 1}).status_code == 409  # nothing to rate yet
    run = client.post(f"/api/my-tasks/{t['id']}/do").json()["mission_id"]
    _finished(client, run)
    d = client.get(f"/api/my-tasks/{t['id']}").json()
    assert d["items_total"] == 0  # a simulation's template steps don't become your checklist
    assert client.post(f"/api/my-tasks/{t['id']}/feedback", json={"rating": 1, "reason": "  "}).json()["reason"] is None
    f = client.post(f"/api/my-tasks/{t['id']}/feedback", json={"rating": -1, "reason": "Too long"}).json()
    assert f["agent"] == "designer"
    assert client.get(f"/api/my-tasks/{t['id']}").json()["feedback"]["reason"] == "Too long"
    q = client.get("/api/insights/agent-quality").json()["agents"][0]
    assert q["agent"] == "designer" and q["down"] == 1 and q["recent_reasons"] == ["Too long"]
    lib = client.get("/api/my-tasks/results", params={"q": "launch email"}).json()["results"]
    assert len(lib) == 1 and lib[0]["task_title"] == "Draft the launch email" and lib[0]["rating"] == -1 and lib[0]["simulated"]
    assert client.get("/api/my-tasks/results", params={"q": "zebra"}).json()["results"] == []
    t2 = _add(client, "draft the welcome email")
    e2 = client.get(f"/api/my-tasks/{t2['id']}/estimate").json()
    assert e2["runs"] == 1 and e2["cost_usd"] is None and "simulations" in e2["note"] and "estimate" in e2["note"]


def test_weekly_review_and_bulk(client):
    a = _add(client, "late thing", due_at="2020-01-01T00:00:00Z")
    b = _add(client, "old idea")
    with transaction() as conn:
        conn.execute(update(db.my_tasks).where(db.my_tasks.c.id == b["id"]).values(created_at="2020-01-01T00:00:00+00:00"))
    r = client.get("/api/my-tasks/review", params={"tz": LA}).json()
    assert [t["title"] for t in r["slipped"]] == ["Late thing"] and [t["title"] for t in r["stale"]] == ["Old idea"]
    out = client.post("/api/my-tasks/bulk", json={"ids": [a["id"], b["id"]], "action": "next_week", "tz": LA}).json()
    assert sorted(out["changed"]) == sorted([a["id"], b["id"]]) and out["errors"] == []
    assert client.get(f"/api/my-tasks/{b['id']}").json()["stage"] == "snoozed"
    out = client.post("/api/my-tasks/bulk", json={"ids": [a["id"], "not-a-task"], "action": "drop"}).json()
    assert out["changed"] == [a["id"]] and out["errors"][0]["task_id"] == "not-a-task"
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.my_tasks.c.status).where(db.my_tasks.c.id == a["id"])).scalar() == "DROPPED"


def test_seed_from_plan_makes_the_checklist(client):
    t = _add(client, "pack for the trip")
    with db.get_engine().connect() as conn:
        org = conn.execute(select(db.my_tasks.c.organization_id)).scalar()
    taskplus.seed_from_plan(org, t["id"], ["Clothes", "Charger"])
    d = client.get(f"/api/my-tasks/{t['id']}").json()
    assert [i["text"] for i in d["items"]] == ["Clothes", "Charger"] and all(i["from_agents"] for i in d["items"])


def test_the_same_add_twice_makes_one_task(client):
    a = _add(client, "call the bank", client_ref="phone-0001-abcd")
    b = _add(client, "call the bank", client_ref="phone-0001-abcd")
    assert a["id"] == b["id"]
    assert len(client.get("/api/my-tasks").json()["tasks"]) == 1
    assert client.post("/api/my-tasks", json={"text": "x y", "client_ref": "bad ref!"}).status_code == 422
