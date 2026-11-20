"""V6.158–V6.187: paste a bill, due-date moves, payment notes and history, the forecast, credit watch and habits,
utilization history, card bills, income goal, best days, wins, selling, owed, round-ups, no-spend days, set-asides,
to-dos, weekly check-in, can I afford it, projections, export and setup."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from services.management import money3

LA = "America/Los_Angeles"


def _today():
    return datetime.now(timezone.utc).astimezone(ZoneInfo(LA)).date()


def _clear():
    from services.core import auth
    auth.mutation_limiter._state.clear()


def _bid(r):
    return r["id"] if "id" in r else r["bill"]["id"]


def test_parse_bill(client):
    _clear()
    text = ("From: PG&E <billing@pge.com>\nYour PG&E bill is ready.\nAccount 1234567890123\nAmount due: $142.17\n"
            "Due date: December 15, 2026\nPrevious balance $120.00")
    r = client.post("/api/money/bills/parse", json={"text": text, "tz": LA}).json()
    assert r["name"] == "PG&E" and r["amount"] == 142.17 and r["due_date"] == "2026-12-15" and r["due_day"] == 15
    assert r["autopay"] is False and r["cadence"] == "monthly"
    r = money3.parse_bill("Comcast: your automatic payment of $89.99 will be charged on 12/03.", LA)
    assert r["amount"] == 89.99 and r["due_day"] == 3 and r["autopay"]
    assert client.post("/api/money/bills/parse", json={"text": " "}).status_code == 422


def test_payment_notes_and_history(client):
    _clear()
    b = client.post("/api/bills", json={"name": "Water", "amount": 40, "due_day": 10, "tz": LA}).json()
    bid = _bid(b)
    client.post(f"/api/bills/{bid}/paid", json={"period": "2026-01", "amount": 40, "tz": LA})
    assert client.put(f"/api/money/bills/{bid}/payment-note", json={"period": "2026-01", "confirmation": "ABC123", "method": "Bank app"}).status_code == 200
    assert client.put(f"/api/money/bills/{bid}/payment-note", json={"period": "2026-02", "confirmation": "x"}).status_code == 409
    assert client.put(f"/api/money/bills/{bid}/payment-note", json={"period": "2026-01", "confirmation": "4111 1111 1111 1111"}).status_code == 422
    h = client.get(f"/api/money/bills/{bid}/history", params={"tz": LA}).json()
    assert h["payments"][0]["confirmation"] == "ABC123" and h["payments"][0]["method"] == "Bank app" and h["average"] == 40
    client.request("DELETE", f"/api/bills/{bid}/paid", params={"period": "2026-01"})
    assert client.get("/api/money/bills/nope/history").status_code == 404


def test_forecast_and_afford(client):
    _clear()
    t = _today()
    assert client.get("/api/money/forecast", params={"tz": LA}).json()["ready"] is False
    client.post("/api/money/accounts", json={"name": "Checking", "balance": 300, "tz": LA})
    client.post("/api/money/pay", json={"name": "Job", "cadence": "weekly", "anchor_day": (t + timedelta(days=4)).isoformat(), "amount": 500})
    due = t + timedelta(days=2)
    client.post("/api/bills", json={"name": "Rent", "amount": 600, "due_day": due.day, "tz": LA})
    f = client.get("/api/money/forecast", params={"tz": LA}).json()
    assert f["ready"] and len(f["days"]) == 31 and f["start"] == 300
    pay_day = next(d for d in f["days"] if any(e["kind"] == "pay" for e in d["events"]))
    assert pay_day["day"] == (t + timedelta(days=4)).isoformat()
    if due.month == t.month:
        assert f["below_zero"] and f["low"]["balance"] < 0
    a = client.get("/api/money/afford", params={"amount": 50, "tz": LA}).json()
    assert a["ready"] and a["verdict"] in ("fits", "tight", "short") and a["why"]
    assert client.get("/api/money/afford", params={"amount": 0}).status_code == 422


def test_credit_watch_disputes_habits(client):
    _clear()
    t = _today()
    w = client.get("/api/money/credit-watch", params={"tz": LA}).json()
    assert [b["bureau"] for b in w["bureaus"]] == ["equifax", "experian", "transunion"] and all(b["due"] for b in w["bureaus"])
    assert w["reports_url"] == "https://www.annualcreditreport.com"
    client.put("/api/money/credit-watch/report/equifax", json={"on": True})
    client.put("/api/money/credit-watch/freeze/experian", json={"on": True})
    w = client.get("/api/money/credit-watch", params={"tz": LA}).json()
    eq = w["bureaus"][0]
    assert eq["due"] is False and eq["days_since"] == 0 and w["bureaus"][1]["frozen"]
    assert client.put("/api/money/credit-watch/report/nope", json={"on": True}).status_code == 404
    d = client.post("/api/money/disputes", json={"bureau": "transunion", "item": "Collection I don't recognize",
                                                 "sent_on": (t - timedelta(days=40)).isoformat(), "tz": LA}).json()
    w = client.get("/api/money/credit-watch", params={"tz": LA}).json()
    assert w["disputes"][0]["follow_up_due"]
    todos = client.get("/api/money/todos", params={"tz": LA}).json()["items"]
    assert any(x["key"] == f"dispute:{d['id']}" for x in todos)
    client.patch(f"/api/money/disputes/{d['id']}", json={"status": "fixed", "tz": LA})
    assert client.get("/api/money/credit-watch", params={"tz": LA}).json()["disputes"][0]["closed_on"]
    h = client.get("/api/money/credit-habits", params={"tz": LA}).json()
    assert {i["key"] for i in h["items"]} >= {"on_time", "utilization", "reports", "accounts"}
    assert client.delete(f"/api/money/disputes/{d['id']}").json() == {"ok": True}


def test_utilization_history_and_card_bill(client):
    _clear()
    c = client.post("/api/money/credit/cards", json={"name": "Blue", "limit": 1000, "balance": 500}).json()
    client.patch(f"/api/money/credit/cards/{c['id']}", json={"balance": 200})
    pts = client.get("/api/money/utilization-history", params={"tz": LA}).json()["points"]
    assert pts and pts[-1]["utilization"] == 0.2  # one point a day, the latest balance
    b = client.put(f"/api/money/credit/cards/{c['id']}/bill", json={"due_day": 22, "tz": LA}).json()
    assert b["name"] == "Blue payment" and b["due_day"] == 22 and b["amount"] is None
    b2 = client.put(f"/api/money/credit/cards/{c['id']}/bill", json={"due_day": 25, "tz": LA}).json()
    assert b2["id"] == b["id"] and b2["due_day"] == 25
    assert client.get("/api/money/card-bills").json()["links"] == {c["id"]: b["id"]}
    client.delete(f"/api/money/credit/cards/{c['id']}")
    assert client.get("/api/money/card-bills").json()["links"] == {}


def test_income_goal_best_days(client):
    _clear()
    t = _today()
    client.put("/api/money/income-goal", json={"monthly": 3000})
    client.post("/api/money/income", json={"amount": 200, "source": "Uber", "hours": 8, "tz": LA})
    g = client.get("/api/money/income-goal", params={"tz": LA}).json()
    assert g["goal"] == 3000 and g["earned"] == 200 and g["left"] == 2800 and g["hourly"] == 25 and g["hours_needed"] == 112
    bd = client.get("/api/money/best-days", params={"tz": LA, "source": "uber"}).json()
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    assert bd["best"] == [names[t.weekday()]] and len(bd["days"]) == 7


def test_wins_selling_owed(client):
    _clear()
    t = _today()
    client.post("/api/money/wins", json={"title": "Internet lowered", "amount": 20, "monthly": True, "tz": LA})
    client.post("/api/money/wins", json={"title": "Late fee waived", "amount": 35, "tz": LA})
    w = client.get("/api/money/wins", params={"tz": LA}).json()
    assert w["this_year"] == 55 and w["per_month_ongoing"] == 20
    i = client.post("/api/money/selling", json={"name": "Old bike", "asking": 150, "where_listed": "Marketplace", "tz": LA}).json()
    s = client.get("/api/money/selling", params={"tz": LA}).json()
    assert s["listed"] == 1 and s["listed_value"] == 150
    client.patch(f"/api/money/selling/{i['id']}", json={"sold": 120, "tz": LA})
    s = client.get("/api/money/selling", params={"tz": LA}).json()
    assert s["listed"] == 0 and s["sold_this_year"] == 120
    o = client.post("/api/money/owed", json={"who": "Jay", "amount": 40, "why": "concert ticket",
                                             "expected_on": (t - timedelta(days=2)).isoformat()}).json()
    ow = client.get("/api/money/owed", params={"tz": LA}).json()
    assert ow["outstanding"] == 40 and ow["late"] == 1
    client.put(f"/api/money/owed/{o['id']}/received", json={"received": True, "tz": LA})
    assert client.get("/api/money/owed", params={"tz": LA}).json()["outstanding"] == 0


def test_round_ups_no_spend_set_asides(client):
    _clear()
    t = _today()
    client.post("/api/money/spending", json={"amount": 4.25, "category": "Fun", "tz": LA})
    client.post("/api/money/spending", json={"amount": 10, "category": "Fun", "tz": LA})
    assert client.get("/api/money/round-ups", params={"tz": LA}).json()["round_ups"] == 0.75
    y = (t - timedelta(days=1)).isoformat()
    y2 = (t - timedelta(days=2)).isoformat()
    client.put("/api/money/no-spend", json={"day": y, "on": True, "tz": LA})
    client.put("/api/money/no-spend", json={"day": y2, "on": True, "tz": LA})
    ns = client.get("/api/money/no-spend", params={"tz": LA}).json()
    assert ns["streak"] == 2 and ns["today"] is False
    client.put("/api/money/no-spend", json={"on": True, "tz": LA})  # today, but spending is logged today
    assert t.isoformat() in client.get("/api/money/no-spend", params={"tz": LA}).json()["conflicts"]
    due_month = (t.month % 12) + 1
    b = client.post("/api/bills", json={"name": "Car insurance", "amount": 1200, "cadence": "yearly", "due_day": 20,
                                        "due_month": due_month, "tz": LA}).json()
    sa = client.get("/api/money/set-asides", params={"tz": LA}).json()
    f = sa["funds"][0]
    assert f["name"] == "Car insurance" and f["per_month"] == round(1200 / f["months"], 2)
    g = client.post(f"/api/money/set-asides/{_bid(b)}/goal", json={"tz": LA})
    assert g.status_code == 201
    pj = client.get("/api/money/projections", params={"tz": LA}).json()["goals"]
    sg = next(x for x in pj if x["name"].startswith("Set aside"))
    assert sg["pace_from"] == "plan" and sg["months"] == f["months"]


def test_assistant_pieces(client):
    _clear()
    s = client.get("/api/money/setup", params={"tz": LA}).json()
    assert s["total"] == 8 and 0 <= s["done"] <= 8
    w = client.get("/api/money/weekly", params={"tz": LA}).json()
    assert set(w) >= {"bills", "safe_per_day", "income_goal", "owed_to_you", "todos"}
    ex = client.get("/api/money/export").json()
    assert "my_bills" in ex["tables"] and all("organization_id" not in r for rows in ex["tables"].values() for r in rows)
    mv = client.get("/api/money/due-date-moves", params={"tz": LA}).json()
    assert "moves" in mv


def test_due_date_move_suggestion():
    assert money3._ordinal(1) == "1st" and money3._ordinal(12) == "12th" and money3._ordinal(23) == "23rd"


def test_money_routes_need_member_or_operator(client):
    import inspect

    from services.api.main import app
    for r in app.routes:
        if not getattr(r, "path", "").startswith("/api/money"):
            continue
        deps = [p.default.dependency.__name__ for p in inspect.signature(r.endpoint).parameters.values() if hasattr(p.default, "dependency")]
        assert ("operator" if r.methods & {"POST", "PUT", "PATCH", "DELETE"} else "member") in deps, r.path


def test_review_fixes_parsing():
    """V6.187 review: amount due not the previous balance, no account numbers in the name, card statements aren't
    yearly, yearless dates nearest today."""
    r = money3.parse_bill("Previous balance $500.00\nAmount due $120.00\nDue Dec 15", LA)
    assert r["amount"] == 120.0
    r = money3.parse_bill("Your Comcast account 8155 1234 5678 9012 bill is ready. Amount due: $1,234.56 by 12/20", LA)
    assert r["name"] == "Comcast" and r["amount"] == 1234.56
    r = money3.parse_bill("Your Chase Freedom card ending in 4821 statement. New balance $310.22. Annual Percentage Rate 24.99%. Payment due 12/18", LA)
    assert r["cadence"] == "monthly" and "4821" not in r["name"] and r["amount"] == 310.22
    assert money3.parse_bill("Your home insurance renews annually. Annual premium $900 due March 3", LA)["cadence"] == "yearly"
    ds = money3._dates("is due Dec 31", date(2027, 1, 3))
    assert ds[0][1] == date(2026, 12, 31)
    ds = money3._dates("due Jan 5", date(2026, 12, 30))
    assert ds[0][1] == date(2027, 1, 5)


def test_review_fixes_data(client):
    _clear()
    # account numbers can't get into a bill
    assert client.post("/api/bills", json={"name": "Comcast 8155 1234 5678", "amount": 10, "due_day": 3}).status_code == 422
    # long confirmation numbers are fine; a card number isn't
    b = client.post("/api/bills", json={"name": "Electric", "amount": 60, "due_day": 3, "tz": LA}).json()
    bid = _bid(b)
    client.post(f"/api/bills/{bid}/paid", json={"period": "2026-03", "amount": 60, "tz": LA})
    assert client.put(f"/api/money/bills/{bid}/payment-note", json={"period": "2026-03", "confirmation": "202611201234567890"}).status_code == 200
    # removing a card switches its payment bill off (history kept)
    c = client.post("/api/money/credit/cards", json={"name": "Green", "limit": 500, "balance": 100}).json()
    cb = client.put(f"/api/money/credit/cards/{c['id']}/bill", json={"due_day": 9, "tz": LA}).json()
    client.delete(f"/api/money/credit/cards/{c['id']}")
    all_bills = client.get("/api/bills", params={"tz": LA, "include_inactive": True}).json()["bills"]
    hit = [x for x in all_bills if x["id"] == cb["id"]]
    assert not hit or hit[0]["active"] is False
    ex = client.get("/api/money/export").json()["tables"]
    assert "money_checks" in ex and "card_bills" in ex


def test_every_money_table_has_row_level_security():
    """Each table created in the money migrations turns on row-level security with a members-only read policy."""
    import pathlib
    import re
    sql = "\n".join(p.read_text() for p in sorted(pathlib.Path("infrastructure/migrations").glob("*.sql")))
    for f in ("0022_money.sql", "0023_money_more.sql", "0024_money_assistant.sql"):
        text = pathlib.Path("infrastructure/migrations", f).read_text()
        for t in re.findall(r"create table (\w+)", text):
            assert f"alter table {t} enable row level security" in sql, t
            assert re.search(rf"create policy \w+ on {t} for select using \(public\.is_member\(organization_id\)\)", sql), t
