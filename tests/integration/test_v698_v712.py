"""V6.98–V6.112: brain dumps, steps that become tasks, bills, the month calendar, a plan around your calendar,
"I have N minutes", the end of the day, weekly goals, waiting for people, the archive, export/import and list styles."""
import csv
import io
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.management import taskextra, taskplus

LA = "America/Los_Angeles"


def _add(client, text, **kw):
    r = client.post("/api/my-tasks", json={"text": text, "tz": LA, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _org():
    with db.get_engine().connect() as conn:
        return conn.execute(select(db.my_tasks.c.organization_id)).scalar()


def test_brain_dump_preview_then_add(client):
    text = "- buy milk tomorrow\n2. call the bank #money 15m\n[ ] read https://example.com/post\n\n  x\n"
    prev = client.post("/api/my-tasks/dump", json={"text": text, "tz": LA}).json()["preview"]
    assert [p["title"] for p in prev] == ["Buy milk", "Call the bank", "Read"]
    assert prev[1]["list_name"] == "money" and prev[1]["estimate_minutes"] == 15 and prev[2]["links"] == ["https://example.com/post"]
    assert client.get("/api/my-tasks").json()["tasks"] == []  # a preview saves nothing
    out = client.post("/api/my-tasks", json={"text": "x y"})  # (sanity: adding still works)
    added = client.post("/api/my-tasks/dump", json={"text": text, "tz": LA, "dry_run": False}).json()
    assert len(added["added"]) == 3 and added["problems"] == [] and out.status_code == 201


def test_csv_import_and_export(client):
    data = "title,list,due,notes,priority,estimate\nFile taxes,money,by apr 15,Use last year's forms,urgent,90\n=cmd(),,,,,\n"
    added = client.post("/api/my-tasks/dump", json={"text": data, "format": "csv", "dry_run": False, "tz": LA}).json()["added"]
    assert added[0]["title"] == "File taxes" and added[0]["list_name"] == "money" and added[0]["priority"] == "urgent"
    assert added[0]["estimate_minutes"] == 90 and added[0]["notes"] == "Use last year's forms"
    assert client.post("/api/my-tasks/dump", json={"text": "name\nx\n", "format": "csv"}).status_code == 422
    j = client.get("/api/my-tasks/export").json()
    assert {t["title"] for t in j["tasks"]} == {"File taxes", "=cmd()"}
    r = client.get("/api/my-tasks/export", params={"format": "csv"})
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][0] == "title" and "'=cmd()" in [x[0] for x in rows]  # formulas are neutralised


def test_promote_a_step(client):
    t = _add(client, "move house #home", items=["Book the van", "Pack"])
    d = client.get(f"/api/my-tasks/{t['id']}").json()
    new = client.post(f"/api/my-tasks/{t['id']}/items/{d['items'][0]['id']}/promote").json()
    assert new["title"] == "Book the van" and new["list_name"] == "home" and "Move house" in new["notes"]
    assert [i["text"] for i in client.get(f"/api/my-tasks/{t['id']}").json()["items"]] == ["Pack"]
    assert client.post(f"/api/my-tasks/{t['id']}/items/not-an-id/promote").status_code == 404


def test_bills(client):
    b = client.post("/api/bills", json={"name": "Phone", "amount": 54.99, "due_day": 31, "autopay": True,
                                        "link_url": "https://carrier.example.com/pay", "tz": LA}).json()
    assert b["amount_cents"] == 5499 and b["autopay"] is True and b["next_due"] and not b["paid_this_period"]
    nd = date.fromisoformat(b["next_due"])
    assert nd.day == taskextra._month_len(nd.year, nd.month)  # the 31st is the last day of shorter months
    paid = client.post(f"/api/bills/{b['id']}/paid", json={"tz": LA}).json()
    assert paid["payments"][0]["period"] == b["period"] and paid["next_due"] > b["next_due"]
    assert client.post(f"/api/bills/{b['id']}/paid", json={"period": b["period"], "tz": LA}).status_code == 409
    assert client.post(f"/api/bills/{b['id']}/paid", json={"period": "2026", "tz": LA}).status_code == 422
    assert client.delete(f"/api/bills/{b['id']}/paid/{b['period']}", params={"tz": LA}).json()["payments"] == []
    y = client.post("/api/bills", json={"name": "Car registration", "amount": 210, "cadence": "yearly", "due_day": 10, "due_month": 6}).json()
    assert y["next_due"].endswith("-06-10") and y["period"].isdigit()
    assert client.post("/api/bills", json={"name": "Bad", "cadence": "yearly", "due_day": 3}).status_code == 422
    assert client.post("/api/bills", json={"name": "Gym", "due_day": 1, "link_url": "javascript:alert(1)//x"}).status_code == 422
    from services.core import auth
    auth.mutation_limiter._state.clear()  # this test makes more changes than the burst allows
    v = client.post("/api/bills", json={"name": "Electric", "due_day": 20}).json()  # amount varies
    s = client.get("/api/bills/summary", params={"tz": LA}).json()
    assert s["varies_count"] >= 1 and s["total"] >= 54.99
    assert client.patch(f"/api/bills/{v['id']}", json={"amount": 80}).json()["amount"] == 80
    assert client.delete(f"/api/bills/{v['id']}").json() == {"ok": True}
    assert client.patch("/api/bills/nope", json={"amount": 1}).status_code == 404


def test_bill_dates():
    bill = {"cadence": "monthly", "due_day": 15, "due_month": None, "created_day": date(2026, 1, 1)}
    assert taskextra.next_due(bill, date(2026, 11, 20), {"2026-11", "2026-10", "2026-09"}) == date(2026, 12, 15)
    assert taskextra.next_due(bill, date(2026, 11, 20), {"2026-10", "2026-09"}) == date(2026, 11, 15)  # unpaid: overdue
    new = {**bill, "created_day": date(2026, 11, 18)}
    assert taskextra.next_due(new, date(2026, 11, 20), set()) == date(2026, 12, 15)  # added after this month's date


def test_month_calendar(client):
    _add(client, "dentist on nov 20")
    client.post("/api/bills", json={"name": "Rent", "amount": 1800, "due_day": 1})
    m = client.get("/api/my-tasks/month", params={"year": 2026, "month": 12, "tz": LA}).json()
    assert m["days"]["2026-12-01"]["bills"][0]["name"] == "Rent"
    assert client.get("/api/my-tasks/month", params={"year": 1990, "month": 1}).status_code == 422


def test_plan_goes_around_busy_times(client):
    _add(client, "write the report 60m urgent")
    org = _org()
    now = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    busy = [(now.replace(hour=9), now.replace(hour=10, minute=30))]
    with db.get_engine().connect() as conn:
        p = taskplus.plan_day(conn, org, "UTC", "09:00", "18:00", now=now, busy=busy)
    kinds = [(b["verb"], b["start"][11:16]) for b in p["blocks"]]
    assert kinds[0] == ("Busy", "09:00") and kinds[1] == ("Do", "10:30") and p["busy_minutes"] == 90
    bad = client.get("/api/my-tasks/plan", params={"busy": "not,times"})
    assert bad.status_code == 422
    ok = client.get("/api/my-tasks/plan", params=[("tz", "UTC"), ("busy", "2026-11-14T09:00:00+00:00,2026-11-14T09:30:00+00:00")])
    assert ok.status_code == 200


def test_fit_in_the_time_you_have(client):
    _add(client, "quick email 10m")
    _add(client, "big refactor 2h")
    _add(client, "old one 20m", due_at="2020-01-01T00:00:00Z")
    f = client.get("/api/my-tasks/fit", params={"minutes": 30, "tz": LA}).json()
    assert [x["title"] for x in f["picks"]] == ["Old one", "Quick email"] and f["left_over"] == 0
    assert client.get("/api/my-tasks/fit", params={"minutes": 2}).status_code == 422


def test_end_of_day(client):
    t = _add(client, "send invoice today at 11pm")
    s = client.get("/api/my-tasks/shutdown", params={"tz": LA}).json()
    assert [x["title"] for x in s["still_due"]] == ["Send invoice"]
    out = client.post("/api/my-tasks/shutdown", json={"tz": LA, "move": True, "note": "Start with the invoice"}).json()
    assert out["moved"] == [t["id"]]
    moved = client.get(f"/api/my-tasks/{t['id']}").json()["due_at"]
    assert datetime.fromisoformat(moved) - datetime.fromisoformat(t["due_at"]) == timedelta(days=1)
    again = client.get("/api/my-tasks/shutdown", params={"tz": LA}).json()
    assert again["note"] == "Start with the invoice" and again["still_due"] == []
    assert again["tomorrow"][0]["title"] == "Send invoice"


def test_weekly_goals(client):
    g = client.post("/api/goals", json={"text": "Ship the Echo beta", "tz": LA}).json()
    gid = g["goals"][0]["id"]
    t = _add(client, "fix the login bug")
    assert client.post(f"/api/my-tasks/{t['id']}/goal", json={"goal_id": gid}).json()["goal_id"] == gid
    client.post(f"/api/my-tasks/{t['id']}/done")
    goals = client.get("/api/goals", params={"tz": LA}).json()["goals"]
    assert goals[0]["progress"] == 1.0 and goals[0]["tasks"][0]["title"] == "Fix the login bug"
    client.post("/api/goals", json={"text": "Two", "tz": LA})
    client.post("/api/goals", json={"text": "Three", "tz": LA})
    assert client.post("/api/goals", json={"text": "Four", "tz": LA}).status_code == 409
    assert client.patch(f"/api/goals/{gid}", json={"done": True, "tz": LA}).json()["goals"][0]["done"] is True
    assert len(client.delete(f"/api/goals/{gid}", params={"tz": LA}).json()["goals"]) == 2
    assert client.get(f"/api/my-tasks/{t['id']}").json()["goal_id"] is None
    assert client.post(f"/api/my-tasks/{t['id']}/goal", json={"goal_id": "nope"}).status_code == 404


def test_waiting_for_people(client):
    t = _add(client, "lease renewal")
    later = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    w = client.post(f"/api/my-tasks/{t['id']}/waiting", json={"person": "Sam", "follow_up_at": later}).json()
    assert w["stage"] == "waiting" and w["waiting_for"]["person"] == "Sam" and not w["follow_up_due"]
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    w = client.post(f"/api/my-tasks/{t['id']}/waiting", json={"person": "Sam", "follow_up_at": past}).json()
    assert w["stage"] == "open" and w["follow_up_due"]  # time to follow up
    assert client.post(f"/api/my-tasks/{t['id']}/waiting", json={"person": "Sam", "follow_up_at": "soon"}).status_code == 422
    assert client.post(f"/api/my-tasks/{t['id']}/waiting", json={}).json()["waiting_for"] is None


def test_archive(client):
    t = _add(client, "old chore")
    client.post(f"/api/my-tasks/{t['id']}/done")
    assert any(x["id"] == t["id"] for x in client.get("/api/my-tasks").json()["tasks"])
    with transaction() as conn:
        conn.execute(update(db.my_tasks).where(db.my_tasks.c.id == t["id"]).values(done_at="2020-01-01T00:00:00+00:00",
                                                                                  updated_at="2020-01-01T00:00:00+00:00"))
    assert not any(x["id"] == t["id"] for x in client.get("/api/my-tasks").json()["tasks"])
    arch = client.get("/api/my-tasks/archive", params={"q": "chore"}).json()["tasks"]
    assert [a["id"] for a in arch] == [t["id"]]
    client.post(f"/api/my-tasks/{t['id']}/reopen")  # restore
    assert any(x["id"] == t["id"] for x in client.get("/api/my-tasks").json()["tasks"])


def test_list_styles(client):
    s = client.put("/api/lists/Home/style", json={"color": "#33aa77", "icon": "house"}).json()["styles"]
    assert s == {"home": {"color": "#33AA77", "icon": "house"}}
    assert client.put("/api/lists/home/style", json={"color": "red", "icon": "house"}).status_code == 422
    assert client.put("/api/lists/home/style", json={"color": "#33aa77", "icon": "rocket.launch.secret"}).status_code == 422
    assert client.put("/api/lists/home/style", json={}).json()["styles"] == {}
    assert "house" in client.get("/api/lists/styles").json()["icons"]


def test_review_fixes_csv(client):
    exported = ("﻿title,status,due,list,priority,estimate,repeat,notes\n"
                "Call mom,OPEN,2026-11-20T17:00:00+00:00,family,low,30,none,ask about thanksgiving\n"
                "'=SUM(A1),OPEN,,,,,,\n"
                "Call Sam, about the lease,OPEN,,,,,,\n")
    prev = client.post("/api/my-tasks/dump", json={"text": exported, "format": "csv", "tz": LA}).json()["preview"]
    assert prev[0]["title"] == "Call mom" and prev[0]["due_at"].startswith("2026-11-20T17:00") and prev[0]["priority"] == "low"
    assert prev[0]["estimate_minutes"] == 30 and prev[0]["list_name"] == "family"
    assert prev[1]["title"] == "=SUM(A1)" and prev[2]["title"].startswith("Call Sam")
    bad = client.post("/api/my-tasks/dump", json={"text": 'title\n"unclosed\n', "format": "csv"})
    assert bad.status_code in (200, 422)


def test_review_fixes_end_of_day_keeps_repeats(client):
    t = _add(client, "standup every day at 9am")
    with transaction() as conn:  # due an hour ago, still open
        conn.execute(update(db.my_tasks).where(db.my_tasks.c.id == t["id"]).values(
            due_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()))
    out = client.post("/api/my-tasks/shutdown", json={"tz": "UTC", "move": True}).json()
    assert out["moved"] == []


def test_review_fixes_bill_added_after_its_day():
    zone = __import__("zoneinfo").ZoneInfo(LA)
    bill = {"cadence": "monthly", "due_day": 11, "due_month": None, "created_day": date(2026, 11, 14)}
    assert taskextra.next_due(bill, date(2026, 11, 14), set()) == date(2026, 12, 11)
    del zone


def test_review_fixes_busy_overlaps_and_old_months(client):
    org = _org() or "00000000-0000-4000-8000-0000000000ff"
    now = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    busy = taskextra.parse_busy([f"{now.replace(hour=10).isoformat()},{now.replace(hour=11).isoformat()}",
                                 f"{now.replace(hour=10, minute=30).isoformat()},{now.replace(hour=11, minute=30).isoformat()}"])
    with db.get_engine().connect() as conn:
        p = taskplus.plan_day(conn, org, "UTC", "09:00", "18:00", now=now, busy=busy)
    assert p["busy_minutes"] == 90 and sum(1 for b in p["blocks"] if b["verb"] == "Busy") == 1
    t = _add(client, "old thing on jan 5")
    client.post(f"/api/my-tasks/{t['id']}/done")
    with transaction() as conn:
        conn.execute(update(db.my_tasks).where(db.my_tasks.c.id == t["id"]).values(
            due_at="2026-01-05T20:00:00+00:00", done_at="2026-01-05T21:00:00+00:00", updated_at="2026-01-05T21:00:00+00:00"))
    m = client.get("/api/my-tasks/month", params={"year": 2026, "month": 1, "tz": LA}).json()
    assert m["days"]["2026-01-05"]["tasks"][0]["title"] == "Old thing"
    s = client.get("/api/lists/styles").json()
    assert "items" in s
