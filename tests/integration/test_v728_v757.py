"""V6.128–V6.157: spending, category limits, balances, safe to spend, debts and payoff, paydown targets, the calendar
feed, bill checks, gigs and the tax set-aside, the checklist, call script, cashback, emergency fund, net worth, the
monthly review, the on-time streak, split bills and the paycheck split."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from services.management import money2

LA = "America/Los_Angeles"


def _today():
    return datetime.now(timezone.utc).astimezone(ZoneInfo(LA)).date()


def _clear():
    from services.core import auth
    auth.mutation_limiter._state.clear()


def test_spending_and_limits(client):
    _clear()
    assert client.post("/api/money/spending", json={"amount": 45.5, "category": "groceries", "tz": LA}).status_code == 201
    client.post("/api/money/spending", json={"amount": 20, "category": "Groceries", "tz": LA})
    client.post("/api/money/spending", json={"amount": 12, "category": "Fun", "tz": LA})
    assert client.put("/api/money/spending/limits", json={"category": "Groceries", "limit": 60}).status_code == 200
    s = client.get("/api/money/spending", params={"tz": LA}).json()
    g = next(c for c in s["categories"] if c["category"] == "Groceries")
    assert s["total"] == 77.5 and g["spent"] == 65.5 and g["limit"] == 60 and g["over"] and g["left"] == -5.5
    assert "Gas" in s["suggested_categories"]
    client.put("/api/money/spending/limits", json={"category": "Groceries", "limit": None})
    s = client.get("/api/money/spending", params={"tz": LA}).json()
    assert next(c for c in s["categories"] if c["category"] == "Groceries")["limit"] is None
    assert client.get("/api/money/spending", params={"month": "2026-13"}).status_code == 422
    future = (_today() + timedelta(days=3)).isoformat()
    assert client.post("/api/money/spending", json={"amount": 1, "category": "x", "day": future, "tz": LA}).status_code == 422
    assert client.delete(f"/api/money/spending/{s['entries'][0]['id']}").json() == {"ok": True}
    assert client.delete("/api/money/spending/not-an-id").status_code == 404


def test_accounts_safe_to_spend_and_low_balance(client):
    _clear()
    t = _today()
    assert client.post("/api/money/accounts", json={"name": "Checking 1234567890", "balance": 10}).status_code == 422  # no numbers
    a = client.post("/api/money/accounts", json={"name": "Checking", "balance": 500, "tz": LA}).json()
    client.post(f"/api/money/accounts/{a['id']}/balance", json={"balance": 400, "tz": LA})  # same day: replaces
    acc = client.get("/api/money/accounts").json()["accounts"][0]
    assert acc["balance"] == 400 and len(acc["history"]) == 1
    client.post("/api/money/pay", json={"name": "Job", "cadence": "weekly", "anchor_day": (t + timedelta(days=6)).isoformat(), "amount": 700})
    due = t + timedelta(days=2)
    client.post("/api/bills", json={"name": "Electric", "amount": 150, "due_day": due.day, "tz": LA})
    s = client.get("/api/money/safe-to-spend", params={"tz": LA}).json()
    assert s["ready"] and s["next_payday"] == (t + timedelta(days=6)).isoformat() and s["days"] == 6
    if due.month == t.month:
        assert s["bills_total"] == 150 and s["left"] == 250 - s["savings_set_aside"] and s["per_day"] == round(max(0, s["left"]) / 6, 2)
    # a big bill before payday: a warning with the shortfall
    client.post("/api/bills", json={"name": "Rent", "amount": 1200, "due_day": due.day, "tz": LA})
    s = client.get("/api/money/safe-to-spend", params={"tz": LA}).json()
    if due.month == t.month:
        assert s["short"] and s["warning"] and s["shortfall"] > 0
    assert client.delete(f"/api/money/accounts/{a['id']}").json() == {"ok": True}
    assert client.get("/api/money/safe-to-spend", params={"tz": LA}).json()["ready"] is False


def test_payoff_simulation():
    d = [{"id": "a", "name": "Card A", "balance": 1000, "apr": 24, "min_payment": 50},
         {"id": "b", "name": "Card B", "balance": 300, "apr": 12, "min_payment": 25}]
    start = date(2026, 1, 15)
    ava = money2.simulate(d, 100, "avalanche", start)
    sno = money2.simulate(d, 100, "snowball", start)
    base = money2.simulate(d, 0, "avalanche", start)
    assert ava["months"] and sno["months"] and base["months"] > ava["months"]
    assert ava["interest"] <= sno["interest"] and base["interest"] > ava["interest"]
    assert sno["order"][0]["name"] == "Card B"  # smallest balance first
    assert ava["order"][-1]["paid_off_month"] == ava["months"]
    stuck = money2.simulate([{"id": "c", "name": "C", "balance": 5000, "apr": 30, "min_payment": 50}], 0, "avalanche", start)
    assert stuck["never"] and stuck["months"] is None  # $50 doesn't cover ~$125 of interest


def test_debts_and_paydown(client):
    _clear()
    c = client.post("/api/money/credit/cards", json={"name": "Blue card", "limit": 2000, "balance": 900, "statement_day": 20}).json()
    d = client.post("/api/money/debts", json={"name": "Blue card", "balance": 900, "apr": 24, "min_payment": 35, "card_id": c["id"]}).json()
    client.post("/api/money/debts", json={"name": "Car loan", "kind": "loan", "balance": 5000, "apr": 6, "min_payment": 200})
    r = client.get("/api/money/debts", params={"extra": 100, "tz": LA}).json()
    blue = next(x for x in r["debts"] if x["name"] == "Blue card")
    assert blue["monthly_interest"] == 18.0 and r["payoff"]["debts"] == 2
    assert r["payoff"]["avalanche"]["order"][0]["name"] == "Blue card" and r["payoff"]["interest_saved_by_extra"] > 0
    pd = client.get("/api/money/paydown", params={"tz": LA}).json()
    card = pd["cards"][0]
    assert card["pay_to_30"] == 300 and card["pay_to_10"] == 700 and card["monthly_interest"] == 18.0 and card["next_statement"]
    assert client.post("/api/money/debts", json={"name": "x", "balance": 1, "apr": 150, "min_payment": 1}).status_code == 422
    assert client.patch(f"/api/money/debts/{d['id']}", json={"card_id": "00000000-0000-4000-8000-000000000000"}).status_code == 404
    client.delete(f"/api/money/credit/cards/{c['id']}")
    assert next(x for x in client.get("/api/money/debts").json()["debts"] if x["id"] == d["id"])["card_id"] is None


def test_calendar_feed(client):
    _clear()
    t = _today()
    client.post("/api/bills", json={"name": "Water, sewer; trash", "amount": 40, "due_day": 10, "tz": LA})
    client.post("/api/money/pay", json={"name": "Job", "cadence": "biweekly", "anchor_day": t.isoformat(), "amount": 900})
    r = client.get("/api/money/calendar.ics", params={"tz": LA})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    body = r.text
    assert body.startswith("BEGIN:VCALENDAR") and body.count("BEGIN:VEVENT") >= 12 + 20
    assert r"SUMMARY:Due: Water\, sewer\; trash $40.00" in body and "SUMMARY:Payday: Job" in body


def test_bill_checks_and_extras(client):
    _clear()
    t = _today()
    a = client.post("/api/money/accounts", json={"name": "Bills account", "balance": 50, "tz": LA}).json()
    due = t + timedelta(days=3)
    b = client.post("/api/bills", json={"name": "Gym", "amount": 80, "due_day": due.day, "autopay": True, "tz": LA}).json()
    bid = b["id"] if "id" in b else b["bill"]["id"]
    client.post("/api/money/pay", json={"name": "Job", "cadence": "weekly", "anchor_day": (t + timedelta(days=5)).isoformat()})
    assert client.put(f"/api/money/bills/{bid}/extras", json={"autopay_account_id": a["id"], "late_fee": 25, "grace_days": 5}).status_code == 200
    ch = client.get("/api/money/bill-checks", params={"tz": LA}).json()
    if due.month == t.month:
        cov = next(x for x in ch["autopay"] if x["account_id"] == a["id"])
        assert cov["covered"] is False and cov["short_by"] == 30
    assert ch["extras"][bid]["late_fee"] == 25
    # an amount that jumped: paid 80, then 95
    client.post(f"/api/bills/{bid}/paid", json={"period": "2026-01", "amount": 80, "tz": LA})
    client.post(f"/api/bills/{bid}/paid", json={"period": "2026-02", "amount": 95, "tz": LA})
    ch = client.get("/api/money/bill-checks", params={"tz": LA}).json()
    jump = next((x for x in ch["amount_changes"] if x["bill_id"] == bid), None)
    assert jump and jump["last"] == 95 and jump["before"] == 80
    assert client.put(f"/api/money/bills/{bid}/extras", json={"grace_days": 99}).status_code == 422
    s = client.get(f"/api/money/bills/{bid}/call-script", params={"years": 3, "competitor_price": 49.99}).json()
    assert "3 years" in s["lines"][0] and "$49.99" in s["lines"][0]
    assert client.get("/api/money/bills/nope/call-script").status_code == 404


def test_gigs_and_tax_set_aside(client):
    _clear()
    client.patch("/api/money/settings", json={"mileage_rate": 0.5, "tax_pct": 25, "gig_sources": ["DoorDash"]})
    client.post("/api/money/income", json={"amount": 200, "source": "DoorDash", "hours": 8, "tz": LA})
    client.post("/api/money/gigs/costs", json={"source": "DoorDash", "amount": 20, "miles": 60, "tz": LA})
    g = client.get("/api/money/gigs", params={"tz": LA}).json()
    dd = g["gigs"][0]
    assert dd["source"] == "DoorDash" and dd["recent"]["mileage"] == 30 and dd["recent"]["net"] == 150
    assert dd["recent"]["hourly_gross"] == 25 and dd["recent"]["hourly_net"] == 18.75
    assert g["year_profit"] == 150 and g["tax_set_aside"] == 37.5
    assert client.post("/api/money/gigs/costs", json={"source": "DoorDash"}).status_code == 422
    assert client.patch("/api/money/settings", json={"tax_pct": 80}).status_code == 422


def test_checklist_cashback_emergency_networth(client):
    _clear()
    cl = client.get("/api/money/checklist").json()
    assert all(i["url"] is None or i["url"].startswith("https://") for i in cl["items"])
    assert client.put("/api/money/checklist/state_unclaimed", json={"done": True}).status_code == 200
    assert next(i for i in client.get("/api/money/checklist").json()["items"] if i["key"] == "state_unclaimed")["done_at"]
    assert client.put("/api/money/checklist/bogus", json={"done": True}).status_code == 404
    client.post("/api/money/cashback", json={"card": "Blue card", "amount": 12.5, "tz": LA})
    client.post("/api/money/cashback", json={"card": "Blue card", "amount": 7.5, "tz": LA})
    cb = client.get("/api/money/cashback", params={"tz": LA}).json()
    assert cb["year_total"] == 20 and cb["by_card"][0]["total"] == 20
    client.post("/api/bills", json={"name": "Rent", "amount": 1000, "due_day": 1, "tz": LA})
    g = client.post("/api/money/savings", json={"name": "Emergency", "target": 6000, "tz": LA}).json()
    client.post(f"/api/money/savings/{g['id']}/deposits", json={"amount": 1500, "tz": LA})
    client.patch("/api/money/settings", json={"emergency_goal_id": g["id"]})
    e = client.get("/api/money/emergency", params={"tz": LA}).json()
    assert e["saved"] == 1500 and e["monthly_bills"] == 1000 and e["months_covered"] == 1.5 and e["for_3_months"] == 1500
    _clear()
    acc = client.post("/api/money/accounts", json={"name": "Checking", "balance": 800, "tz": LA}).json()
    client.post("/api/money/net-worth/assets", json={"name": "Car", "value": 6000})
    client.post("/api/money/debts", json={"name": "Car loan", "kind": "loan", "balance": 4000, "apr": 7, "min_payment": 150})
    nw = client.get("/api/money/net-worth", params={"tz": LA}).json()
    assert nw["assets"] == 6800 and nw["debts"] == 4000 and nw["net"] == 2800
    assert client.post("/api/money/net-worth/snapshot", params={"tz": LA}).json()["net"] == 2800
    client.post("/api/money/net-worth/snapshot", params={"tz": LA})  # once a day: replaced
    assert len(client.get("/api/money/net-worth", params={"tz": LA}).json()["snapshots"]) == 1
    client.delete(f"/api/money/savings/{g['id']}")
    assert client.get("/api/money/settings").json()["emergency_goal_id"] is None
    client.delete(f"/api/money/accounts/{acc['id']}")


def test_review_streak_splits_paycheck(client):
    _clear()
    t = _today()
    r = client.get("/api/money/review", params={"tz": LA}).json()
    prev = (t.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    assert r["month"] == prev and "streak" in r
    client.post("/api/money/income", json={"amount": 300, "source": "Job", "tz": LA})
    client.post("/api/money/spending", json={"amount": 100, "category": "Fun", "tz": LA})
    r = client.get("/api/money/review", params={"tz": LA, "month": t.strftime("%Y-%m")}).json()
    assert r["income"] == 300 and r["spending"] == 100 and r["kept"] == 200 and r["highlights"]
    b = client.post("/api/bills", json={"name": "Internet", "amount": 90, "due_day": 28, "tz": LA}).json()
    bid = b["id"] if "id" in b else b["bill"]["id"]
    s = client.post(f"/api/money/bills/{bid}/splits", json={"person": "Sam", "share": 30}).json()
    sp = client.get("/api/money/splits", params={"tz": LA}).json()
    e = sp["bills"][0]
    assert e["your_share"] == 60 and sp["owed_to_you"] == 30
    assert client.put(f"/api/money/splits/{s['id']}/received", json={"period": e["period"]}).status_code == 200
    assert client.get("/api/money/splits", params={"tz": LA}).json()["owed_to_you"] == 0
    assert client.put(f"/api/money/splits/{s['id']}/received", json={"period": "26-1"}).status_code == 422
    client.delete(f"/api/bills/{bid}")
    assert client.get("/api/money/splits", params={"tz": LA}).json()["bills"] == []
    st = client.get("/api/money/streak", params={"tz": LA}).json()
    assert set(st) == {"current", "best", "counted"}
    assert client.get("/api/money/paycheck-split", params={"tz": LA}).json()["ready"] is False
    client.post("/api/money/pay", json={"name": "Job", "cadence": "biweekly", "anchor_day": (t - timedelta(days=2)).isoformat(), "amount": 1400})
    ps = client.get("/api/money/paycheck-split", params={"tz": LA}).json()
    assert ps["ready"] and ps["pay"] == 1400 and round(ps["bills"] + ps["savings"] + ps["spending"], 2) == 1400


def test_reads_need_member_and_writes_need_operator(client):
    from services.api.main import app
    routes = [r for r in app.routes if getattr(r, "path", "").startswith("/api/money")]
    import inspect
    for r in routes:
        deps = [p.default.dependency.__name__ for p in inspect.signature(r.endpoint).parameters.values()
                if hasattr(p.default, "dependency")]
        if r.methods & {"POST", "PUT", "PATCH", "DELETE"}:
            assert "operator" in deps, r.path
        else:
            assert "member" in deps, r.path
