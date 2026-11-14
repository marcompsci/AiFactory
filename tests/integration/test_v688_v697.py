"""V6.88–V6.97: search, undo, each task's history, links, smarter repeats, streaks and the morning digest."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.management import taskmore
from services.management.capture import next_due, parse

LA = "America/Los_Angeles"
NOW = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)  # Friday 10am in Los Angeles


def _add(client, text, **kw):
    r = client.post("/api/my-tasks", json={"text": text, "tz": LA, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_smarter_repeats_parse():
    cases = {
        "pay rent on the 1st of every month": ("Pay rent", "monthly", "Dec 1 5:00 PM"),
        "water plants every 3 days": ("Water plants", "days:3", "today 5:00 PM"),
        "team sync every other week on tuesday": ("Team sync", "biweekly", "Tue 5:00 PM"),
        "pay card on the last day of the month": ("Pay card", "monthly_last", "Nov 30 5:00 PM"),
        "renew domain every year": ("Renew domain", "yearly", "today 5:00 PM"),
        "review on the 30th of every month": ("Review", "monthly:30", "Nov 30 5:00 PM"),
        "budget monthly on the 31st": ("Budget", "monthly_last", "Nov 30 5:00 PM"),
    }
    for text, (title, rep, label) in cases.items():
        r = parse(text, LA, now=NOW)
        assert (r["title"], r["repeat"], r["due_label"]) == (title, rep, label), text
    assert parse("every 400 days stretch", LA, now=NOW)["repeat"] == "none"


def test_smarter_repeats_schedule():
    def run(due, rep, n=5):
        out, a = [], due
        for _ in range(n):
            a = next_due(a, rep, LA, after=datetime.fromisoformat(a))
            out.append(datetime.fromisoformat(a).astimezone(__import__("zoneinfo").ZoneInfo(LA)).strftime("%b %d %H:%M"))
        return out
    assert run(parse("x on the 30th of every month", LA, now=NOW)["due_at"], "monthly:30") == \
        ["Dec 30 17:00", "Jan 30 17:00", "Feb 28 17:00", "Mar 30 17:00", "Apr 30 17:00"]  # keeps 5pm through DST
    assert run(parse("x on the last day of the month", LA, now=NOW)["due_at"], "monthly_last", 3) == \
        ["Dec 31 17:00", "Jan 31 17:00", "Feb 28 17:00"]
    assert run("2026-11-13T01:00:00+00:00", "biweekly", 2) == ["Nov 26 17:00", "Dec 10 17:00"]
    assert run("2026-11-13T01:00:00+00:00", "days:3", 2) == ["Nov 15 17:00", "Nov 18 17:00"]
    # a missed stretch is skipped, not piled up
    nxt = next_due("2026-01-15T01:00:00+00:00", "monthly", LA, after=NOW)
    assert datetime.fromisoformat(nxt) > NOW and datetime.fromisoformat(nxt) < NOW + timedelta(days=32)


def test_repeat_values_are_checked(client):
    t = _add(client, "stretch")
    assert client.patch(f"/api/my-tasks/{t['id']}", json={"repeat": "days:14"}).json()["repeat_label"] == "every 14 days"
    assert client.patch(f"/api/my-tasks/{t['id']}", json={"repeat": "days:1"}).status_code == 422
    assert client.patch(f"/api/my-tasks/{t['id']}", json={"repeat": "hourly"}).status_code == 422


def test_search(client):
    a = _add(client, "book flights #travel", items=["Check baggage rules"])
    b = _add(client, "call the dentist")
    client.patch(f"/api/my-tasks/{b['id']}", json={"notes": "ask about the cleaning"})
    ids = lambda q: [t["id"] for t in client.get("/api/my-tasks", params={"q": q}).json()["tasks"]]
    assert ids("travel") == [a["id"]]          # its list
    assert ids("baggage") == [a["id"]]         # its checklist
    assert ids("cleaning dentist") == [b["id"]]  # every word, across title and notes
    assert ids("zebra") == []
    assert len(ids("")) == 2


def test_undo_done_removes_the_untouched_repeat(client):
    t = _add(client, "gym every day")
    out = client.post(f"/api/my-tasks/{t['id']}/done", json={"tz": LA}).json()
    nxt = out["next"]["id"]
    u = client.post(f"/api/my-tasks/{t['id']}/undo-done").json()
    assert u["task"]["stage"] == "open" and u["removed_next"] == nxt
    assert client.get(f"/api/my-tasks/{nxt}").status_code == 404
    assert client.post(f"/api/my-tasks/{t['id']}/undo-done").status_code == 409  # it isn't done any more
    # done again: a fresh next one, and an edited next one is kept on undo
    nxt2 = client.post(f"/api/my-tasks/{t['id']}/done", json={"tz": LA}).json()["next"]["id"]
    client.patch(f"/api/my-tasks/{nxt2}", json={"notes": "leg day"})
    assert client.post(f"/api/my-tasks/{t['id']}/undo-done").json()["removed_next"] is None
    assert client.post("/api/my-tasks/not-an-id/undo-done").status_code == 404


def test_history(client):
    t = _add(client, "renew passport")
    client.patch(f"/api/my-tasks/{t['id']}", json={"notes": "photos first"})
    client.post(f"/api/my-tasks/{t['id']}/snooze", json={"preset": "tomorrow", "tz": LA})
    client.post(f"/api/my-tasks/{t['id']}/done")
    h = client.get(f"/api/my-tasks/{t['id']}/history").json()["history"]
    texts = [x["text"] for x in h]
    assert texts[0].startswith("Marked done") and "Snoozed" in texts and "Changed the notes" in texts and texts[-1] == "Added"
    other = _add(client, "something else")
    assert all("something" not in x["text"] for x in client.get(f"/api/my-tasks/{other['id']}/history").json()["history"])
    assert client.get("/api/my-tasks/nope/history").status_code == 404


def test_links(client):
    t = _add(client, "read https://example.com/guide?x=1, then summarize")
    assert t["title"] == "Read then summarize" or t["title"].startswith("Read")
    d = client.get(f"/api/my-tasks/{t['id']}").json()
    assert [l["url"] for l in d["links"]] == ["https://example.com/guide?x=1"] and d["links"][0]["host"] == "example.com"
    links = client.post(f"/api/my-tasks/{t['id']}/links", json={"url": "https://docs.example.org/a", "title": "Docs"}).json()["links"]
    assert len(links) == 2 and links[1]["title"] == "Docs"
    assert len(client.post(f"/api/my-tasks/{t['id']}/links", json={"url": "https://docs.example.org/a"}).json()["links"]) == 2
    for bad in ("javascript:alert(1)//", "ftp://example.com/file", "https://user:pw@example.com/x"):
        assert client.post(f"/api/my-tasks/{t['id']}/links", json={"url": bad}).status_code == 422, bad
    assert client.delete(f"/api/my-tasks/{t['id']}/links/{links[1]['id']}").json()["links"][0]["url"].startswith("https://example.com")
    assert client.delete(f"/api/my-tasks/{t['id']}/links/not-an-id").status_code == 404
    assert [x["id"] for x in client.get("/api/my-tasks", params={"q": "example"}).json()["tasks"]] == [t["id"]]
    prev = client.get("/api/my-tasks/parse", params={"text": "watch https://youtu.be/abc every 2 weeks", "tz": LA}).json()
    assert prev["links"] == ["https://youtu.be/abc"] and prev["repeat_label"] == "every 2 weeks" and prev["title"] == "Watch"


def test_streaks():
    assert taskmore.streak_of(["done", "done", "late", "done", "done", "open"]) == (2, 2)
    assert taskmore.streak_of(["done", "done", "done", "missed", "done"]) == (1, 3)
    assert taskmore.streak_of([]) == (0, 0)


def test_habits_follow_the_chain(client):
    t = _add(client, "meditate every day")
    first = t["id"]
    nxt = client.post(f"/api/my-tasks/{first}/done", json={"tz": LA}).json()["next"]["id"]
    nxt2 = client.post(f"/api/my-tasks/{nxt}/done", json={"tz": LA}).json()["next"]["id"]
    with transaction() as conn:  # the second one was finished two days after it was due
        due = conn.execute(select(db.my_tasks.c.due_at).where(db.my_tasks.c.id == nxt)).scalar()
        late = (datetime.fromisoformat(due) + timedelta(days=2)).isoformat()
        conn.execute(update(db.my_tasks).where(db.my_tasks.c.id == nxt).values(done_at=late))
    h = client.get("/api/my-tasks/habits", params={"tz": LA}).json()["habits"]
    assert len(h) == 1 and h[0]["task_id"] == nxt2 and h[0]["times"] == 2
    assert [r["outcome"] for r in h[0]["recent"]] == ["done", "late", "open"] and h[0]["current"] == 0 and h[0]["best"] == 1
    assert client.get(f"/api/my-tasks/{nxt2}").json()["streak"] == {"current": 0, "best": 1, "times": 2}


def test_digest(client):
    _add(client, "pay the phone bill today")
    _add(client, "old one", due_at="2020-01-01T00:00:00Z")
    _add(client, "someday thing")
    d = client.get("/api/my-tasks/digest", params={"tz": "UTC"}).json()
    assert d["overdue"] == 1 and d["title"].startswith("Today:") and "1 overdue" in d["title"]
    assert "Old one" in d["body"]
    with db.get_engine().connect() as conn:
        org = conn.execute(select(db.my_tasks.c.organization_id)).scalar()
        empty = taskmore.digest(conn, "00000000-0000-4000-8000-0000000000ff", "UTC", "tomorrow")
        assert empty["title"] == "Tomorrow: nothing due" and empty["body"] == "A clear day on your list."
        assert taskmore.digest(conn, org, LA, "today")["due"] >= 0
    assert client.get("/api/my-tasks/digest", params={"day": "yesterday"}).status_code == 422


def test_review_fixes_repeats():
    from services.management.capture import valid_repeat
    assert not valid_repeat("daily\n") and not valid_repeat("days:1٣") and valid_repeat("days:365") and not valid_repeat("days:366")
    zone = __import__("zoneinfo").ZoneInfo(LA)
    # plain monthly from the 31st comes back to the 31st; yearly from Feb 29 returns in leap years
    first = "2026-02-01T01:00:00+00:00"  # Jan 31, 5pm in Los Angeles
    a, days = first, []
    for _ in range(3):
        a = next_due(a, "monthly", LA, after=datetime.fromisoformat(a), anchor=first)
        days.append(datetime.fromisoformat(a).astimezone(zone).strftime("%b %d"))
    assert days == ["Feb 28", "Mar 31", "Apr 30"]
    leap = "2028-03-01T01:00:00+00:00"  # Feb 29, 2028
    a, years = leap, []
    for _ in range(4):
        a = next_due(a, "yearly", LA, after=datetime.fromisoformat(a), anchor=leap)
        years.append(datetime.fromisoformat(a).astimezone(zone).strftime("%Y-%m-%d"))
    assert years == ["2029-02-28", "2030-02-28", "2031-02-28", "2032-02-29"]


def test_review_fixes_links_and_search(client):
    t = _add(client, "pay the card bill every month")
    for bad in ("http://[abc/x", "http://ab", "https://exa\x00mple.com/x"):
        assert client.post(f"/api/my-tasks/{t['id']}/links", json={"url": bad}).status_code == 422, bad
    links = client.post(f"/api/my-tasks/{t['id']}/links", json={"url": "HTTPS://bank.example.com/pay"}).json()["links"]
    assert links[0]["url"] == "https://bank.example.com/pay"
    nxt = client.post(f"/api/my-tasks/{t['id']}/done", json={"tz": LA}).json()["next"]
    assert [l["url"] for l in client.get(f"/api/my-tasks/{nxt['id']}").json()["links"]] == ["https://bank.example.com/pay"]
    _add(client, "купить молоко")
    assert [x["title"] for x in client.get("/api/my-tasks", params={"q": "молоко"}).json()["tasks"]] == ["Купить молоко"]
    assert client.get("/api/my-tasks", params={"q": "!!"}).json()["tasks"] == []
    assert client.post("/api/my-tasks", json={"text": "see http://[abc/x now"}).status_code == 201


def test_undo_keeps_a_repeat_you_worked_on(client):
    t = _add(client, "water the plants every 3 days", items=["Ferns"])
    nxt = client.post(f"/api/my-tasks/{t['id']}/done", json={"tz": LA}).json()["next"]
    item = client.get(f"/api/my-tasks/{nxt['id']}").json()["items"][0]["id"]
    client.patch(f"/api/my-tasks/{nxt['id']}/items/{item}", json={"done": True})  # ticked a step on the next one
    assert client.post(f"/api/my-tasks/{t['id']}/undo-done").json()["removed_next"] is None
    assert client.get(f"/api/my-tasks/{nxt['id']}").status_code == 200


def test_digest_counts_each_task_once(client):
    _add(client, "old one", due_at="2020-01-01T00:00:00Z")
    with db.get_engine().connect() as conn:
        org = conn.execute(select(db.my_tasks.c.organization_id)).scalar()
        d = taskmore.digest(conn, org, "UTC", "3")
    assert d["overdue"] == 1 and d["body"].count("Old one") == 1 and not d["title"].startswith(("Today", "Tomorrow"))
