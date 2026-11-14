"""V6.113–V6.127: income, paydays, the payday planner, savings goals, the budget, subscriptions, find savings, credit
utilization, the on-time record, bills in quick capture and the money overview."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.management import money

LA = "America/Los_Angeles"


def _today():
    return datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(LA)).date()


def _clear():
    from services.core import auth
    auth.mutation_limiter._state.clear()


def test_income_totals_and_rate(client):
    t = _today()
    client.post("/api/money/income", json={"amount": 120, "source": "Rideshare", "hours": 6, "tz": LA})
    client.post("/api/money/income", json={"amount": 30, "source": "Rideshare", "hours": 2, "tz": LA})
    client.post("/api/money/income", json={"amount": 200, "source": "Paycheck", "tz": LA})
    i = client.get("/api/money/income", params={"tz": LA}).json()
    assert i["week_total"] == 350 and i["week_hourly"] == 18.75  # (120 + 30) / 8 hours
    assert i["by_source"][0]["source"] == "Paycheck" and len(i["weeks"]) == 8 and i["weeks"][-1]["total"] == 350
    future = (t + timedelta(days=2)).isoformat()
    assert client.post("/api/money/income", json={"amount": 5, "source": "x", "day": future, "tz": LA}).status_code == 422
    eid = i["entries"][0]["id"]
    assert client.delete(f"/api/money/income/{eid}").json() == {"ok": True}
    assert client.delete("/api/money/income/nope").status_code == 404


def test_paydays():
    s = {"cadence": "biweekly", "anchor_day": "2026-11-06"}
    assert money.paydays(s, date(2026, 11, 14), 3) == [date(2026, 11, 20), date(2026, 12, 4), date(2026, 12, 18)]
    s = {"cadence": "semimonthly", "anchor_day": "2026-11-15"}
    assert money.paydays(s, date(2026, 11, 16), 3) == [date(2026, 11, 30), date(2026, 12, 15), date(2026, 12, 31)]
    s = {"cadence": "monthly", "anchor_day": "2026-01-31"}
    assert money.paydays(s, date(2027, 2, 1), 2) == [date(2027, 2, 28), date(2027, 3, 31)]
    s = {"cadence": "weekly", "anchor_day": "2026-11-13"}
    assert money.paydays(s, date(2026, 11, 13), 2) == [date(2026, 11, 13), date(2026, 11, 20)]


def test_planner_and_budget(client):
    t = _today()
    anchor = (t - timedelta(days=3)).isoformat()
    assert client.post("/api/money/pay", json={"name": "Job", "cadence": "weekly", "anchor_day": anchor, "amount": 500}).status_code == 201
    due = (t + timedelta(days=2))
    client.post("/api/bills", json={"name": "Phone", "amount": 60, "due_day": due.day, "tz": LA})
    pl = client.get("/api/money/planner", params={"tz": LA}).json()
    assert pl["has_schedule"] and len(pl["periods"]) == 4
    first = pl["periods"][0]
    if due.month == t.month:  # the bill falls in this pay period
        assert any(b["name"] == "Phone" for b in first["bills"]) and first["needed"] >= 60 and first["left"] == first["pay"] - first["needed"]
    client.post("/api/money/savings", json={"name": "Emergency fund", "target": 1000, "monthly_plan": 100, "tz": LA})
    b = client.get("/api/money/budget", params={"tz": LA}).json()
    assert b["savings_plan"] == 100 and b["left"] == round(b["income"] - b["bills"] - 100, 2)
    assert client.post("/api/money/pay", json={"cadence": "daily", "anchor_day": anchor}).status_code == 422


def test_savings_goals(client):
    _clear()
    t = _today()
    g = client.post("/api/money/savings", json={"name": "Laptop", "target": 1200, "deadline": (t + timedelta(days=28)).isoformat(),
                                                "tz": LA}).json()
    goals = client.post(f"/api/money/savings/{g['id']}/deposits", json={"amount": 400, "tz": LA}).json()["goals"]
    lap = next(x for x in goals if x["id"] == g["id"])
    assert lap["saved"] == 400 and lap["left"] == 800 and lap["per_week_needed"] == 200 and lap["progress"] == round(400 / 1200, 3)
    goals = client.post(f"/api/money/savings/{g['id']}/deposits", json={"amount": -100, "tz": LA}).json()["goals"]
    assert next(x for x in goals if x["id"] == g["id"])["saved"] == 300
    assert client.post("/api/money/savings", json={"name": "x", "target": 10, "deadline": "2020-01-01"}).status_code == 422
    assert client.post(f"/api/money/savings/{g['id']}/deposits", json={"amount": 0}).status_code == 422
    assert client.delete(f"/api/money/savings/{g['id']}").json() == {"ok": True}


def test_subscriptions_and_find_savings(client):
    _clear()
    b = client.post("/api/bills", json={"name": "Streaming", "amount": 15.99, "due_day": 3}).json()
    client.post("/api/bills", json={"name": "Rent", "amount": 1800, "due_day": 1})
    s = client.post(f"/api/money/bills/{b['id']}/subscription", json={"subscription": True}).json()
    assert [x["name"] for x in s["subscriptions"]] == ["Streaming"] and s["yearly_total"] == round(15.99 * 12, 2)
    assert s["subscriptions"][0]["review_due"]
    s = client.post(f"/api/money/bills/{b['id']}/subscription", json={"reviewed": True}).json()
    assert not s["subscriptions"][0]["review_due"]
    bills = client.get("/api/bills").json()["bills"]
    assert next(x for x in bills if x["id"] == b["id"])["subscription"] is True
    task = client.post(f"/api/money/bills/{b['id']}/find-savings").json()
    assert task["title"] == "Find a cheaper option than Streaming" and task["kind"] == "research" and task["stage"] == "open"
    assert "don't sign up for, cancel or buy" in task["notes"] and task["mission"] is None  # not started
    assert client.post("/api/money/bills/nope/find-savings").status_code == 404


def test_credit(client):
    _clear()
    a = client.post("/api/money/credit/cards", json={"name": "Blue card", "limit": 1000, "balance": 250, "statement_day": 20}).json()
    assert a["utilization"] == 0.25 and a["band"] == "10–30%"
    client.post("/api/money/credit/cards", json={"name": "Store card", "limit": 1000, "balance": 50})
    c = client.get("/api/money/credit", params={"tz": LA}).json()
    assert c["utilization"] == 0.15 and "not advice" in c["note"] and "next_statement" in c["cards"][0]
    assert client.post("/api/money/credit/cards", json={"name": "4111 1111 1111 1111", "limit": 500}).status_code == 422
    assert client.patch(f"/api/money/credit/cards/{a['id']}", json={"balance": 0}).json()["utilization"] == 0
    assert client.delete(f"/api/money/credit/cards/{a['id']}").json() == {"ok": True}


def test_on_time_record(client):
    _clear()
    t = _today()
    b = client.post("/api/bills", json={"name": "Phone", "amount": 50, "due_day": 10, "tz": LA}).json()
    with transaction() as conn:  # added three months ago
        conn.execute(update(db.my_bills).where(db.my_bills.c.id == b["id"]).values(
            created_at=(datetime.now(timezone.utc) - timedelta(days=95)).isoformat()))
    months = []
    y, m = t.year, t.month
    for _ in range(3):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        months.append((y, m))
    (y1, m1), (y2, m2) = months[0], months[1]  # last month: on time; the one before: late
    client.post(f"/api/bills/{b['id']}/paid", json={"period": f"{y1:04d}-{m1:02d}", "paid_on": date(y1, m1, 9).isoformat(), "tz": LA})
    client.post(f"/api/bills/{b['id']}/paid", json={"period": f"{y2:04d}-{m2:02d}", "paid_on": date(y2, m2, 12).isoformat(), "tz": LA})
    r = client.get("/api/money/on-time", params={"tz": LA, "months": 4}).json()
    by = {x["month"]: x for x in r["months"]}
    assert by[f"{y1:04d}-{m1:02d}"]["on_time"] == 1 and by[f"{y2:04d}-{m2:02d}"]["late"] == 1
    assert r["on_time"] >= 1 and r["late"] == 1
    assert client.post(f"/api/bills/{b['id']}/paid", json={"paid_on": (t + timedelta(days=3)).isoformat(), "tz": LA}).status_code == 422


def test_bill_hint_and_overview(client):
    h = money.bill_hint("phone bill $54.99 on the 15th every month")
    assert h == {"name": "Phone bill", "amount": 54.99, "due_day": 15, "cadence": "monthly", "due_month": None}
    y = money.bill_hint("car insurance $600 a year due March 1st")
    assert y == {"name": "Car insurance", "amount": 600.0, "due_day": 1, "cadence": "yearly", "due_month": 3}
    assert money.bill_hint("buy milk tomorrow") is None
    assert money.bill_hint("car insurance $1,200 every year")["amount"] == 1200 and money.bill_hint("car insurance $1,200 every year")["cadence"] == "yearly"
    prev = client.get("/api/my-tasks/parse", params={"text": "pay rent $1800 on the 1st every month", "tz": LA}).json()
    assert prev["bill_hint"]["amount"] == 1800 and prev["bill_hint"]["due_day"] == 1
    _clear()
    client.post("/api/money/income", json={"amount": 80, "source": "Rideshare", "tz": LA})
    o = client.get("/api/money/overview", params={"tz": LA}).json()
    assert o["income_this_week"] == 80 and "bills_due_soon" in o and "savings" in o


def test_review_fixes_money(client):
    from datetime import date
    # a first payday in the future isn't preceded by made-up ones
    assert money.paydays({"cadence": "biweekly", "anchor_day": "2026-12-01"}, date(2026, 11, 13), 2) == [date(2026, 12, 1), date(2026, 12, 15)]
    _clear()
    t = _today()
    anchor = (t - timedelta(days=2)).isoformat()
    client.post("/api/money/pay", json={"name": "Job", "cadence": "weekly", "anchor_day": anchor, "amount": 800})
    client.post("/api/money/pay", json={"name": "Gig", "cadence": "weekly", "anchor_day": anchor})  # same days, amount varies
    pl = client.get("/api/money/planner", params={"tz": LA}).json()  # used to crash sorting None against 800
    assert pl["periods"][0]["pay"] == 800 and "Job + Gig" in pl["periods"][0]["payday"]
    g = client.post("/api/money/savings", json={"name": "Trip", "target": 500, "tz": LA}).json()
    client.post(f"/api/money/savings/{g['id']}/deposits", json={"amount": 50, "tz": LA})
    assert client.post(f"/api/money/savings/{g['id']}/deposits", json={"amount": -80, "tz": LA}).status_code == 422
