"""Even more for the task list (V6.98–V6.112): brain dumps, steps that become tasks, bills, the month calendar, a plan
that works around your calendar, "I have N minutes", the end of the day, weekly goals, waiting for people, the archive,
export and import, and list colors.

Bills are tracked, never paid: the app has no way to move money. You pay a bill wherever you pay it, then mark it paid
here. Calendar times come from your phone as plain start/end times; event titles never reach the server.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.auth import Principal
from services.core.events import emit, transaction

from .taskplus import PlusError, _now, _task, _zone, clean_list, minutes_of

ARCHIVE_DAYS = 30
MAX_DUMP = 50
ICONS = ("tag", "house", "briefcase", "cart", "heart", "dollarsign.circle", "book", "car", "airplane", "dumbbell",
         "graduationcap", "hammer", "leaf", "music.note", "paintbrush", "person.2", "star", "gamecontroller", "camera",
         "skateboard", "figure.run", "fork.knife", "phone", "laptopcomputer")
COLOR_RX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _day(v) -> str:
    return v.isoformat() if isinstance(v, (date, datetime)) else str(v)[:10]


# ---------------------------------------------------------------- V6.98 brain dump, V6.109 import

def _lines(text: str) -> list[str]:
    out = []
    for raw in (text or "").splitlines():
        line = re.sub(r"^\s*(?:[-*•–]|\d+[.)]|\[[ xX]?\])\s*", "", raw).strip()  # bullets, numbers, [ ] boxes
        if len(line) >= 2:
            out.append(line[:400])
    return out


def _csv_rows(text: str) -> list[dict]:
    """A CSV with a header: title (required), and optionally due, list, notes, priority, estimate."""
    reader = csv.DictReader(io.StringIO((text or "").lstrip("\ufeff")))  # a byte-order mark from Excel is ignored
    try:
        if not reader.fieldnames or "title" not in [(f or "").strip().lower() for f in reader.fieldnames]:
            raise PlusError("a CSV needs a header row with a title column")
        rows = []
        for r in reader:
            extra = r.pop(None, None)  # more fields than the header (an unquoted comma): they belong to the last column
            r = {(k or "").strip().lower(): (v if isinstance(v, str) else "").strip() for k, v in r.items()}
            if extra and reader.fieldnames:
                last = (reader.fieldnames[-1] or "").strip().lower()
                r[last] = ", ".join([r.get(last, "")] + [str(x).strip() for x in extra if str(x).strip()]).strip(", ")
            for k, v in r.items():  # undo the export's guard against spreadsheet formulas
                if v[:2] in ("'=", "'+", "'-", "'@"):
                    r[k] = v[1:]
            if len(r.get("title", "")) >= 2:
                rows.append(r)
            if len(rows) >= MAX_DUMP:
                break
        return rows
    except csv.Error as exc:
        raise PlusError(f"that CSV couldn't be read ({exc})") from exc


def dump_preview(text: str, tz: str | None = "UTC", fmt: str = "lines") -> list[dict]:
    """What a brain dump or import would add, one entry per task, without saving anything."""
    from .capture import parse, repeat_label
    from .taskmore import take_urls
    out = []
    if fmt == "csv":
        from .capture import valid_repeat
        from .taskplus import clean_list
        for r in _csv_rows(text)[:MAX_DUMP]:
            # columns are read as what they are (a date, a priority, minutes); only a due date in words is parsed
            due_iso = None
            due = r.get("due", "")
            if due:
                try:
                    d = datetime.fromisoformat(due.replace("Z", "+00:00"))
                    due_iso = (d if d.tzinfo else d.replace(tzinfo=_zone(tz))).astimezone(timezone.utc).isoformat()
                except ValueError:
                    due_iso = None
            line = r["title"] if due_iso or not due else f"{r['title']} {due}"
            rest, urls = take_urls(line)
            p = parse(rest, tz)
            if due_iso:
                p["due_at"], p["due_label"] = due_iso, None
            if r.get("priority", "").lower() in ("urgent", "normal", "low"):
                p["priority"] = r["priority"].lower()
            est = r.get("estimate", "")
            if est.isdigit() and 5 <= int(est) <= 600:
                p["estimate_minutes"] = int(est)
            try:
                if r.get("list"):
                    p["list_name"] = clean_list(r["list"])
            except PlusError:
                pass
            if valid_repeat(r.get("repeat", "")):
                p["repeat"] = r["repeat"]
            p["notes"] = r.get("notes", "")[:4000]
            urls += [u for u in r.get("links", "").split() if u.startswith(("http://", "https://"))]
            p["links"], p["repeat_label"], p["source"] = urls[:20], repeat_label(p["repeat"]), r["title"]
            out.append(p)
        return out
    for line in _lines(text)[:MAX_DUMP]:
        rest, urls = take_urls(line)
        p = parse(rest, tz)
        if len(p["title"]) >= 2:
            p["links"], p["repeat_label"], p["source"] = urls, repeat_label(p["repeat"]), line
            out.append(p)
    return out


def dump_add(p: Principal, text: str, tz: str | None = "UTC", fmt: str = "lines") -> dict:
    """Adds every task a brain dump or import names. Each is checked first, so a bad line stops nothing else."""
    from . import mytasks
    added, problems = [], []
    for item in dump_preview(text, tz, fmt):
        fields = {k: item[k] for k in ("title", "kind", "priority", "due_at", "repeat", "budget_usd", "list_name", "estimate_minutes")}
        if item.get("notes"):
            fields["notes"] = item["notes"]
        if item.get("links"):
            fields["links"] = item["links"]
        try:
            added.append(mytasks.create(p, fields))
        except (mytasks.TaskError, PlusError) as exc:
            problems.append({"line": item["source"], "error": str(exc)})
    return {"added": added, "problems": problems}


# ---------------------------------------------------------------- V6.99 a step becomes a task

def promote_item(p: Principal, tid: str, iid: str) -> dict:
    from . import mytasks
    from .mytasks import _canonical
    I = db.task_items
    with db.get_engine().connect() as conn:
        r = _task(conn, p.organization_id, tid)
        item = conn.execute(select(I).where(I.c.id == iid, I.c.task_id == tid, I.c.organization_id == p.organization_id)).first() \
            if _canonical(iid) else None
        if item is None:
            raise PlusError("step not found", 404)
        from .taskplus import meta_for
        lst = (meta_for(conn, p.organization_id, [tid]).get(tid) or {}).get("list_name")
    title = item.text if len(item.text) >= 2 else f"{item.text} ({r.title})"
    new = mytasks.create(p, {"title": title[:160], "notes": f"A step from \"{r.title}\".", "list_name": lst,
                             "priority": r.priority})
    with transaction() as conn:
        conn.execute(delete(I).where(I.c.id == iid))
        emit(conn, "my_task.updated", org_id=p.organization_id, payload={"task_id": tid, "fields": ["checklist"]})
    return new


# ---------------------------------------------------------------- V6.100–V6.101 bills

def _clean_bill(f: dict, partial: bool = False) -> dict:
    from .taskmore import clean_url
    out: dict = {}
    if "name" in f or not partial:
        n = " ".join(str(f.get("name") or "").split())
        if not 1 <= len(n) <= 80:
            raise PlusError("give the bill a name of up to 80 characters")
        out["name"] = n
    if "amount" in f:
        a = f["amount"]
        if a is None or a == "":
            out["amount_cents"] = None
        else:
            try:
                cents = round(float(a) * 100)
            except (TypeError, ValueError) as exc:
                raise PlusError("the amount is a number like 54.99") from exc
            if not 0 <= cents <= 100_000_000:
                raise PlusError("the amount is between $0 and $1,000,000")
            out["amount_cents"] = cents
    if "cadence" in f or not partial:
        c = f.get("cadence") or "monthly"
        if c not in ("monthly", "yearly"):
            raise PlusError("a bill is monthly or yearly")
        out["cadence"] = c
    if "due_day" in f or not partial:
        d = f.get("due_day")
        if not isinstance(d, int) or not 1 <= d <= 31:
            raise PlusError("the due day is 1 to 31 (31 means the last day of shorter months)")
        out["due_day"] = d
    if "due_month" in f:
        m = f.get("due_month")
        if m is not None and not (isinstance(m, int) and 1 <= m <= 12):
            raise PlusError("the month is 1 to 12")
        out["due_month"] = m
    if "autopay" in f:
        out["autopay"] = int(bool(f["autopay"]))
    if "link_url" in f:
        out["link_url"] = clean_url(f["link_url"]) if f["link_url"] else None
    if "notes" in f:
        out["notes"] = str(f["notes"] or "")[:1000]
    if "remind_days" in f:
        r = f["remind_days"]
        if not isinstance(r, int) or not 0 <= r <= 14:
            raise PlusError("remind 0 to 14 days before")
        out["remind_days"] = r
    if "active" in f:
        out["active"] = int(bool(f["active"]))
    return out


def _month_len(y: int, m: int) -> int:
    return ((date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)).day


def due_date(bill, year: int, month: int | None = None) -> date:
    """When a bill is due in a month (monthly) or a year (yearly); the 31st means the last day of a shorter month."""
    m = month if bill["cadence"] == "monthly" else bill["due_month"]
    return date(year, m, min(bill["due_day"], _month_len(year, m)))


def period_of(bill, d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}" if bill["cadence"] == "monthly" else f"{d.year:04d}"


def next_due(bill, today: date, paid: set[str]) -> date:
    """The earliest due date that isn't paid: an unpaid one that has passed comes first (it's overdue)."""
    if bill["cadence"] == "monthly":
        y, m = today.year, today.month
        cands = []
        for k in range(-2, 13):  # two months back for overdue, a year ahead
            yy, mm = divmod(m - 1 + k, 12)
            cands.append(due_date(bill, y + yy, mm + 1))
    else:
        cands = [due_date(bill, today.year + k) for k in (-1, 0, 1, 2)]
    created = bill.get("created_day")
    for d in sorted(cands):
        if created and d < created:
            continue  # nothing was owed before you added the bill
        if period_of(bill, d) not in paid and (d >= today or (today - d).days <= 62):
            return d
    return sorted(c for c in cands if c >= today)[0]


def _bill_view(r, payments: list, today: date, zone=timezone.utc) -> dict:
    d = dict(r._mapping)
    d["autopay"], d["active"] = bool(d["autopay"]), bool(d["active"])
    d["created_day"] = datetime.fromisoformat(str(d["created_at"]).replace("Z", "+00:00")).astimezone(zone).date() \
        if d.get("created_at") else None
    paid = {p.period for p in payments}
    nd = next_due(d, today, paid)
    d["next_due"] = nd.isoformat()
    d["days_until"] = (nd - today).days
    d["overdue"] = nd < today
    d["period"] = period_of(d, nd)
    this_due = due_date(d, today.year, today.month) if d["cadence"] == "monthly" else due_date(d, today.year)
    this_period = period_of(d, this_due)
    d["paid_this_period"] = this_period in paid
    d["this_period"] = this_period
    # owed this month (or year) only if its date there came on or after the day you added it
    d["owed_this_period"] = not (d["created_day"] and this_due < d["created_day"])
    d["payments"] = [{"period": p.period, "paid_at": p.paid_at, "amount_cents": p.amount_cents} for p in payments][:12]
    d["amount"] = d["amount_cents"] / 100 if d["amount_cents"] is not None else None
    d.pop("created_day", None)
    return d


def bills(conn: Connection, org: str, tz: str | None = "UTC", include_inactive: bool = False) -> list[dict]:
    B, P = db.my_bills, db.my_bill_payments
    today = _now().astimezone(_zone(tz)).date()
    q = select(B).where(B.c.organization_id == org)
    if not include_inactive:
        q = q.where(B.c.active == 1)
    rows = conn.execute(q).fetchall()
    pays: dict[str, list] = {}
    if rows:
        for pr in conn.execute(select(P).where(P.c.organization_id == org, P.c.bill_id.in_([r.id for r in rows]))
                               .order_by(P.c.period.desc())):
            pays.setdefault(pr.bill_id, []).append(pr)
    out = [_bill_view(r, pays.get(r.id, []), today, _zone(tz)) for r in rows]
    out.sort(key=lambda b: (not b["active"], b["next_due"], b["name"].lower()))
    return out


def bill_summary(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """This month's bills: the total, what's paid and unpaid, what's overdue, and what's due in the next 30 days.
    Bills with no fixed amount are counted, not added up."""
    today = _now().astimezone(_zone(tz)).date()
    items = bills(conn, org, tz)
    month = [b for b in items if (b["cadence"] == "monthly" or b["due_month"] == today.month) and b["owed_this_period"]]
    known = [b for b in month if b["amount_cents"] is not None]
    paid = [b for b in month if b["paid_this_period"]]
    soon = [b for b in items if not b["overdue"] and 0 <= b["days_until"] <= 30]
    return {"month": today.strftime("%Y-%m"), "total": round(sum(b["amount_cents"] for b in known) / 100, 2),
            "paid": round(sum(b["amount_cents"] for b in paid if b["amount_cents"] is not None) / 100, 2),
            "unpaid_count": len(month) - len(paid), "varies_count": len(month) - len(known),
            "overdue": [{"id": b["id"], "name": b["name"], "due": b["next_due"]} for b in items if b["overdue"]],
            "next_30_days": [{"id": b["id"], "name": b["name"], "due": b["next_due"], "amount": b["amount"],
                              "autopay": b["autopay"]} for b in soon],
            "next_30_total": round(sum(b["amount_cents"] or 0 for b in soon) / 100, 2)}


def _bill(conn: Connection, org: str, bid: str):
    from .mytasks import _canonical
    r = conn.execute(select(db.my_bills).where(db.my_bills.c.id == bid, db.my_bills.c.organization_id == org)).first() \
        if _canonical(bid) else None
    if r is None:
        raise PlusError("bill not found", 404)
    return r


def _one_bill(org: str, bid: str, tz: str | None) -> dict:
    with db.get_engine().connect() as conn:
        b = next((x for x in bills(conn, org, tz, include_inactive=True) if x["id"] == bid), None)
        if b is None:
            raise PlusError("bill not found", 404)
        return b


def add_bill(p: Principal, fields: dict, tz: str | None = "UTC") -> dict:
    f = _clean_bill(fields)
    if f["cadence"] == "yearly" and not f.get("due_month"):
        raise PlusError("a yearly bill needs its month")
    bid = db.new_id()
    with transaction() as conn:
        n = conn.execute(select(db.my_bills.c.id).where(db.my_bills.c.organization_id == p.organization_id)).fetchall()
        if len(n) >= 100:
            raise PlusError("you can track up to 100 bills", 409)
        conn.execute(insert(db.my_bills).values(id=bid, organization_id=p.organization_id, created_by=p.user_id,
                                             created_at=_now().isoformat(), **f))
        emit(conn, "bill.changed", org_id=p.organization_id, payload={"bill_id": bid, "name": f["name"], "change": "added"})
    return _one_bill(p.organization_id, bid, tz)


def edit_bill(p: Principal, bid: str, fields: dict, tz: str | None = "UTC") -> dict:
    f = _clean_bill(fields, partial=True)
    with transaction() as conn:
        r = _bill(conn, p.organization_id, bid)
        cadence = f.get("cadence", r.cadence)
        if cadence == "yearly" and not f.get("due_month", r.due_month):
            raise PlusError("a yearly bill needs its month")
        if f:
            conn.execute(update(db.my_bills).where(db.my_bills.c.id == bid).values(**f))
        emit(conn, "bill.changed", org_id=p.organization_id, payload={"bill_id": bid, "name": r.name, "change": "edited"})
    return _one_bill(p.organization_id, bid, tz)


def remove_bill(p: Principal, bid: str) -> None:
    with transaction() as conn:
        r = _bill(conn, p.organization_id, bid)
        conn.execute(delete(db.my_bill_payments).where(db.my_bill_payments.c.bill_id == bid))
        conn.execute(delete(db.bill_meta).where(db.bill_meta.c.bill_id == bid))
        conn.execute(delete(db.my_bills).where(db.my_bills.c.id == bid))
        emit(conn, "bill.changed", org_id=p.organization_id, payload={"bill_id": bid, "name": r.name, "change": "removed"})


PERIOD_RX = re.compile(r"^\d{4}(-(0[1-9]|1[0-2]))?$")


def mark_paid(p: Principal, bid: str, period: str | None = None, amount=None, tz: str | None = "UTC",
              paid_on: str | None = None) -> dict:
    """You paid it (somewhere else): record it for one period, on the day you paid (default today; V6.121 uses it for
    your on-time record). The app moves no money."""
    when = _now()
    if paid_on:
        try:
            d = date.fromisoformat(paid_on)
        except ValueError as exc:
            raise PlusError("the day you paid is YYYY-MM-DD") from exc
        zone = _zone(tz)
        if d > when.astimezone(zone).date() or d < when.astimezone(zone).date() - timedelta(days=400):
            raise PlusError("the day you paid can't be in the future or over a year ago")
        when = datetime.combine(d, time(12, 0), tzinfo=zone)
    with transaction() as conn:
        r = _bill(conn, p.organization_id, bid)
        b = next(x for x in bills(conn, p.organization_id, tz, include_inactive=True) if x["id"] == bid)
        per = period or b["period"]
        if not PERIOD_RX.match(per) or (r.cadence == "monthly") != ("-" in per):
            raise PlusError("the period is YYYY-MM for a monthly bill, YYYY for a yearly one")
        cents = _clean_bill({"amount": amount}, partial=True).get("amount_cents") if amount not in (None, "") else r.amount_cents
        P = db.my_bill_payments
        if conn.execute(select(P.c.id).where(P.c.bill_id == bid, P.c.period == per)).first():
            raise PlusError("that period is already marked paid", 409)
        conn.execute(insert(P).values(id=db.new_id(), bill_id=bid, organization_id=p.organization_id, period=per,
                                      amount_cents=cents, paid_at=when.astimezone(timezone.utc).isoformat(), created_by=p.user_id))
        emit(conn, "bill.paid", org_id=p.organization_id, payload={"bill_id": bid, "name": r.name, "period": per})
    return _one_bill(p.organization_id, bid, tz)


def unmark_paid(p: Principal, bid: str, period: str, tz: str | None = "UTC") -> dict:
    with transaction() as conn:
        r = _bill(conn, p.organization_id, bid)
        gone = conn.execute(delete(db.my_bill_payments).where(db.my_bill_payments.c.bill_id == bid,
                                                           db.my_bill_payments.c.period == period)).rowcount
        if not gone:
            raise PlusError("that period wasn't marked paid", 404)
        emit(conn, "bill.changed", org_id=p.organization_id, payload={"bill_id": bid, "name": r.name, "change": "unpaid", "period": period})
    return _one_bill(p.organization_id, bid, tz)


# ---------------------------------------------------------------- V6.102 the month calendar

def month(conn: Connection, org: str, year: int, mon: int, tz: str | None = "UTC") -> dict:
    """Tasks (by due day, in your time zone) and bills (by due day) for one month."""
    from .mytasks import listing
    if not (2000 <= year <= 2100 and 1 <= mon <= 12):
        raise PlusError("that month is out of range")
    zone = _zone(tz)
    days: dict[str, dict] = {}
    first = date(year, mon, 1)
    last = date(year, mon, _month_len(year, mon))
    for t in listing(conn, org, include_done=True, archived=True):
        if not t["due_at"]:
            continue
        d = datetime.fromisoformat(t["due_at"]).astimezone(zone).date()
        if first <= d <= last:
            days.setdefault(d.isoformat(), {"tasks": [], "bills": []})["tasks"].append(
                {"id": t["id"], "title": t["title"], "stage": t["stage"], "list_name": t.get("list_name")})
    for b in bills(conn, org, tz):
        if b["cadence"] == "yearly" and b["due_month"] != mon:
            continue
        d = due_date(b, year, mon)
        days.setdefault(d.isoformat(), {"tasks": [], "bills": []})["bills"].append(
            {"id": b["id"], "name": b["name"], "amount": b["amount"], "autopay": b["autopay"],
             "paid": period_of(b, d) in {x["period"] for x in b["payments"]}})
    return {"year": year, "month": mon, "days": days}


# ---------------------------------------------------------------- V6.103 busy times from your calendar

def parse_busy(raw: list[str], limit: int = 60) -> list[tuple[datetime, datetime]]:
    """"start,end" ISO pairs from the phone's calendar (times only; titles never leave the phone)."""
    out = []
    for item in raw[:limit]:
        try:
            a, b = item.split(",", 1)
            s = datetime.fromisoformat(a.strip().replace("Z", "+00:00"))
            e = datetime.fromisoformat(b.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise PlusError("busy times are start,end pairs") from exc
        if s.tzinfo is None or e.tzinfo is None or e <= s or (e - s) > timedelta(days=1):
            raise PlusError("busy times need a time zone and an end after the start")
        out.append((s, e))
    merged: list[tuple[datetime, datetime]] = []  # overlapping events count once
    for s, e in sorted(out):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


# ---------------------------------------------------------------- V6.104 "I have N minutes"

def fit(conn: Connection, org: str, minutes: int, tz: str | None = "UTC") -> dict:
    """The best open tasks that fit in the time you have: overdue and due-soon first, then priority; each for its
    estimate (or a default by kind, marked so). Nothing is started."""
    from .mytasks import PRIORITY_RANK, listing
    if not 5 <= minutes <= 480:
        raise PlusError("say between 5 minutes and 8 hours")
    zone = _zone(tz)
    end_today = datetime.combine(_now().astimezone(zone).date(), time(23, 59), tzinfo=zone).astimezone(timezone.utc).isoformat()
    tasks = [t for t in listing(conn, org, include_done=False) if t["stage"] in ("open", "problem")]
    tasks.sort(key=lambda t: (not t["overdue"], not (t["due_at"] and t["due_at"] <= end_today),
                              PRIORITY_RANK.get(t["priority"], 1), t["due_at"] or "9999", t["created_at"]))
    left, picks = minutes, []
    for t in tasks:
        m = minutes_of(t)
        if m <= left:
            picks.append({"task_id": t["id"], "title": t["title"], "minutes": m, "estimated": not t.get("estimate_minutes"),
                          "overdue": t["overdue"], "list_name": t.get("list_name")})
            left -= m
        if left < 5:
            break
    return {"minutes": minutes, "picks": picks, "left_over": left}


# ---------------------------------------------------------------- V6.105 the end of the day

def _bounds(tz: str | None, now: datetime | None = None):
    zone = _zone(tz)
    local = (now or _now()).astimezone(zone)
    start = datetime.combine(local.date(), time(0, 0), tzinfo=zone)
    return zone, local.date(), start.astimezone(timezone.utc).isoformat(), (start + timedelta(days=1)).astimezone(timezone.utc).isoformat()


def shutdown(conn: Connection, org: str, tz: str | None = "UTC", now: datetime | None = None) -> dict:
    """Today at a glance before you stop: what you finished, what's still due today, and tomorrow."""
    from .mytasks import listing
    zone, today, start, end = _bounds(tz, now)
    T = db.my_tasks
    done = conn.execute(select(T.c.id, T.c.title).where(T.c.organization_id == org, T.c.status == "DONE",
                                                        T.c.done_at >= start, T.c.done_at < end)).fetchall()
    open_ = listing(conn, org, include_done=False)
    left = [t for t in open_ if t["due_at"] and t["due_at"] < end and t["stage"] in ("open", "problem", "blocked", "waiting")]
    for t in left:
        t["repeats"] = t.get("repeat", "none") != "none"
    tomorrow_end = (datetime.fromisoformat(end) + timedelta(days=1)).isoformat()
    tomorrow = [t for t in open_ if t["due_at"] and end <= t["due_at"] < tomorrow_end]
    note = conn.execute(select(db.day_notes.c.note).where(db.day_notes.c.organization_id == org,
                                                          db.day_notes.c.day == today.isoformat())).scalar()
    yesterday = conn.execute(select(db.day_notes.c.note).where(db.day_notes.c.organization_id == org,
                                                               db.day_notes.c.day == (today - timedelta(days=1)).isoformat())).scalar()
    return {"day": today.isoformat(), "done": [{"id": r.id, "title": r.title} for r in done],
            "still_due": [{"id": t["id"], "title": t["title"], "due_at": t["due_at"], "overdue": t["overdue"], "repeats": t["repeats"]}
                          for t in left],
            "tomorrow": [{"id": t["id"], "title": t["title"], "due_at": t["due_at"]} for t in tomorrow],
            "note": note or "", "yesterdays_note": yesterday or ""}


def close_day(p: Principal, tz: str | None = "UTC", move: bool = False, note: str | None = None, now: datetime | None = None) -> dict:
    """Leave a note for tomorrow and, if you say so, move what's still due today (or overdue) to the same time
    tomorrow. Repeating tasks keep their schedule; nothing is marked done or dropped."""
    zone, today, start, end = _bounds(tz, now)
    moved = []
    with db.get_engine().connect() as conn:
        due = shutdown(conn, p.organization_id, tz, now)["still_due"] if move else []
    with transaction() as conn:
        T = db.my_tasks
        for t in due:
            r = conn.execute(select(T.c.due_at, T.c.repeat).where(T.c.id == t["id"], T.c.organization_id == p.organization_id)).first()
            if r is None or not r.due_at or r.repeat != "none":
                continue  # a repeating task keeps its own schedule
            old = datetime.fromisoformat(r.due_at).astimezone(zone)
            new = datetime.combine(today + timedelta(days=1), old.time(), tzinfo=zone)
            conn.execute(update(T).where(T.c.id == t["id"]).values(due_at=new.astimezone(timezone.utc).isoformat(),
                                                                   updated_at=_now().isoformat()))
            emit(conn, "my_task.updated", org_id=p.organization_id, payload={"task_id": t["id"], "fields": ["due_at"], "moved": "tomorrow"})
            moved.append(t["id"])
        N = db.day_notes
        text = (note or "").strip()[:1000]
        have = conn.execute(select(N.c.day).where(N.c.organization_id == p.organization_id, N.c.day == today.isoformat())).first()
        if have:
            conn.execute(update(N).where(N.c.organization_id == p.organization_id, N.c.day == today.isoformat())
                         .values(note=text, moved=len(moved)))
        else:
            conn.execute(insert(N).values(organization_id=p.organization_id, day=today.isoformat(), note=text, moved=len(moved),
                                          created_at=_now().isoformat()))
        emit(conn, "day.closed", org_id=p.organization_id, payload={"day": today.isoformat(), "moved": len(moved)})
    return {"day": today.isoformat(), "moved": moved, "note": text}


# ---------------------------------------------------------------- V6.106 weekly goals

def week_of(tz: str | None, now: datetime | None = None) -> date:
    local = (now or _now()).astimezone(_zone(tz)).date()
    return local - timedelta(days=local.weekday())


def goals(conn: Connection, org: str, tz: str | None = "UTC", week: str | None = None) -> dict:
    G, TG, T = db.week_goals, db.task_goals, db.my_tasks
    ws = week or week_of(tz).isoformat()
    rows = conn.execute(select(G).where(G.c.organization_id == org, G.c.week_start == ws).order_by(G.c.position)).fetchall()
    out = []
    for g in rows:
        linked = conn.execute(select(T.c.id, T.c.title, T.c.status).join(TG, TG.c.task_id == T.c.id)
                              .where(TG.c.goal_id == g.id, T.c.organization_id == org)).fetchall()
        done = sum(1 for t in linked if t.status == "DONE")
        out.append({"id": g.id, "text": g.text, "done": bool(g.done), "position": g.position,
                    "tasks": [{"id": t.id, "title": t.title, "status": t.status} for t in linked],
                    "progress": round(done / len(linked), 2) if linked else (1.0 if g.done else 0.0),
                    "tasks_done": done})
    return {"week_start": _day(ws), "goals": out}


def add_goal(p: Principal, text: str, tz: str | None = "UTC") -> dict:
    t = " ".join((text or "").split())
    if not 1 <= len(t) <= 120:
        raise PlusError("a goal is 1 to 120 characters")
    ws = week_of(tz).isoformat()
    G = db.week_goals
    with transaction() as conn:
        n = conn.execute(select(G.c.id).where(G.c.organization_id == p.organization_id, G.c.week_start == ws)).fetchall()
        if len(n) >= 3:
            raise PlusError("three goals a week keeps them meaningful; finish or remove one first", 409)
        conn.execute(insert(G).values(id=db.new_id(), organization_id=p.organization_id, week_start=ws, position=len(n), text=t,
                                      done=0, created_at=_now().isoformat()))
        emit(conn, "goal.changed", org_id=p.organization_id, payload={"week_start": ws, "change": "added"})
    with db.get_engine().connect() as conn:
        return goals(conn, p.organization_id, tz)


def _goal(conn: Connection, org: str, gid: str):
    from .mytasks import _canonical
    r = conn.execute(select(db.week_goals).where(db.week_goals.c.id == gid, db.week_goals.c.organization_id == org)).first() \
        if _canonical(gid) else None
    if r is None:
        raise PlusError("goal not found", 404)
    return r


def edit_goal(p: Principal, gid: str, fields: dict, tz: str | None = "UTC") -> dict:
    vals: dict = {}
    if "text" in fields:
        t = " ".join(str(fields["text"] or "").split())
        if not 1 <= len(t) <= 120:
            raise PlusError("a goal is 1 to 120 characters")
        vals["text"] = t
    if "done" in fields:
        vals["done"] = int(bool(fields["done"]))
    with transaction() as conn:
        g = _goal(conn, p.organization_id, gid)
        if vals:
            conn.execute(update(db.week_goals).where(db.week_goals.c.id == gid).values(**vals))
        emit(conn, "goal.changed", org_id=p.organization_id, payload={"week_start": _day(g.week_start), "change": "edited"})
    with db.get_engine().connect() as conn:
        return goals(conn, p.organization_id, tz, _day(g.week_start))


def remove_goal(p: Principal, gid: str, tz: str | None = "UTC") -> dict:
    with transaction() as conn:
        g = _goal(conn, p.organization_id, gid)
        conn.execute(delete(db.task_goals).where(db.task_goals.c.goal_id == gid))
        conn.execute(delete(db.week_goals).where(db.week_goals.c.id == gid))
        emit(conn, "goal.changed", org_id=p.organization_id, payload={"week_start": _day(g.week_start), "change": "removed"})
    with db.get_engine().connect() as conn:
        return goals(conn, p.organization_id, tz, _day(g.week_start))


def link_goal(p: Principal, tid: str, gid: str | None, tz: str | None = "UTC") -> None:
    TG = db.task_goals
    with transaction() as conn:
        _task(conn, p.organization_id, tid)
        conn.execute(delete(TG).where(TG.c.task_id == tid))
        if gid:
            g = _goal(conn, p.organization_id, gid)
            if _day(g.week_start) != week_of(tz).isoformat():
                raise PlusError("tasks can count toward this week's goals")
            conn.execute(insert(TG).values(task_id=tid, goal_id=gid, organization_id=p.organization_id))
        emit(conn, "my_task.updated", org_id=p.organization_id, payload={"task_id": tid, "fields": ["goal"]})


def goal_for(conn: Connection, org: str, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    TG = db.task_goals
    return {r.task_id: r.goal_id for r in conn.execute(select(TG).where(TG.c.organization_id == org, TG.c.task_id.in_(ids)))}


# ---------------------------------------------------------------- V6.107 waiting for people

def waiting_for(conn: Connection, org: str, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    W = db.task_waiting
    return {r.task_id: {"person": r.person, "follow_up_at": r.follow_up_at}
            for r in conn.execute(select(W).where(W.c.organization_id == org, W.c.task_id.in_(ids)))}


def set_waiting(p: Principal, tid: str, person: str | None, follow_up_at: str | None) -> None:
    """Waiting for someone ("Sam, about the lease") until a follow-up date; clear it with no person."""
    W = db.task_waiting
    name = " ".join((person or "").split())[:60]
    when = None
    if name:
        try:
            when = datetime.fromisoformat((follow_up_at or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise PlusError("give a follow-up date") from exc
        if when.tzinfo is None:
            raise PlusError("the follow-up date needs a time zone")
    with transaction() as conn:
        r = _task(conn, p.organization_id, tid)
        if r.status != "OPEN" and name:
            raise PlusError("only open tasks can wait for someone", 409)
        conn.execute(delete(W).where(W.c.task_id == tid))
        if name:
            conn.execute(insert(W).values(task_id=tid, organization_id=p.organization_id, person=name,
                                          follow_up_at=when.astimezone(timezone.utc).isoformat(), created_at=_now().isoformat()))
        emit(conn, "my_task.updated", org_id=p.organization_id, payload={"task_id": tid, "fields": ["waiting_for"]})


# ---------------------------------------------------------------- V6.108 the archive

def archive_cutoff(now: datetime | None = None) -> str:
    return ((now or _now()) - timedelta(days=ARCHIVE_DAYS)).isoformat()


def archive(conn: Connection, org: str, q: str | None = None, limit: int = 100) -> list[dict]:
    """Done and dropped tasks closed more than 30 days ago, newest first; searchable."""
    from .taskmore import search_ids
    T = db.my_tasks
    cut = archive_cutoff()
    rows = conn.execute(select(T.c.id, T.c.title, T.c.status, T.c.done_at, T.c.updated_at, T.c.due_at)
                        .where(T.c.organization_id == org, T.c.status.in_(("DONE", "DROPPED")))
                        .order_by(T.c.updated_at.desc())).fetchall()
    old = [r for r in rows if ((r.done_at or r.updated_at) or "") < cut]
    if q and q.strip():
        hits = search_ids(conn, org, q)
        old = [r for r in old if r.id in hits]
    return [{"id": r.id, "title": r.title, "status": r.status, "closed_at": r.done_at or r.updated_at} for r in old[:limit]]


# ---------------------------------------------------------------- V6.109 export

def export(conn: Connection, org: str, fmt: str = "json") -> tuple[str, str]:
    """Every task (archived ones too) with its list, estimate, checklist and links, as JSON or CSV."""
    from .taskmore import links_for
    from .taskplus import items_for, meta_for
    T = db.my_tasks
    rows = conn.execute(select(T).where(T.c.organization_id == org).order_by(T.c.created_at)).fetchall()
    ids = [r.id for r in rows]
    metas, items, links = meta_for(conn, org, ids), items_for(conn, org, ids), links_for(conn, org, ids)
    data = []
    for r in rows:
        m = metas.get(r.id) or {}
        data.append({"id": r.id, "title": r.title, "notes": r.notes, "status": r.status, "kind": r.kind, "priority": r.priority,
                     "due_at": r.due_at, "repeat": r.repeat, "list": m.get("list_name"), "estimate_minutes": m.get("estimate_minutes"),
                     "created_at": r.created_at, "done_at": r.done_at,
                     "checklist": [{"text": i["text"], "done": i["done"]} for i in items.get(r.id, [])],
                     "links": [ln["url"] for ln in links.get(r.id, [])]})
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["title", "status", "due", "list", "priority", "estimate", "repeat", "notes", "checklist", "links", "created", "done"])
        for d in data:
            cells = [d["title"], d["status"], d["due_at"] or "", d["list"] or "", d["priority"], d["estimate_minutes"] or "",
                     d["repeat"], d["notes"], " | ".join(("[x] " if c["done"] else "[ ] ") + c["text"] for c in d["checklist"]),
                     " ".join(d["links"]), d["created_at"], d["done_at"] or ""]
            # a cell that a spreadsheet would run as a formula starts with a quote instead
            w.writerow(["'" + c if isinstance(c, str) and c[:1] in ("=", "+", "-", "@", "\t", "\r") else c for c in cells])
        return buf.getvalue(), "text/csv"
    return json.dumps({"exported_at": _now().isoformat(), "tasks": data}, indent=1), "application/json"


# ---------------------------------------------------------------- V6.110 list colors and icons

def list_styles(conn: Connection, org: str) -> dict[str, dict]:
    S = db.list_styles
    return {r.list_name: {"color": r.color, "icon": r.icon} for r in conn.execute(select(S).where(S.c.organization_id == org))}


def set_list_style(p: Principal, name: str, color: str | None, icon: str | None) -> dict[str, dict]:
    n = clean_list(name)
    if not n:
        raise PlusError("name the list")
    S = db.list_styles
    with transaction() as conn:
        conn.execute(delete(S).where(S.c.organization_id == p.organization_id, S.c.list_name == n))
        if color or icon:
            if not COLOR_RX.match(color or ""):
                raise PlusError("a color is #RRGGBB")
            if icon not in ICONS:
                raise PlusError("pick one of the listed icons")
            conn.execute(insert(S).values(organization_id=p.organization_id, list_name=n, color=color.upper(), icon=icon))
    with db.get_engine().connect() as conn:
        return list_styles(conn, p.organization_id)
