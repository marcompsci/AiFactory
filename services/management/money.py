"""Money (V6.113–V6.127): income you log, paydays, a payday planner, savings goals, a monthly budget, subscriptions,
"find savings" research tasks, credit-card utilization, your on-time record and a money overview.

Everything here is worked out from numbers you type in. Nothing is connected to a bank, nothing moves money, and
nothing here is financial advice: utilization is shown as a plain ratio with the general rules of thumb many lenders
publish, not as a score.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.auth import Principal
from services.core.events import emit, transaction

from .taskextra import _day, _month_len, bills, due_date, period_of
from .taskplus import PlusError, _now, _zone

CADENCES = ("weekly", "biweekly", "semimonthly", "monthly")
MAX_CENTS = 100_000_000


def _today(tz: str | None) -> date:
    return _now().astimezone(_zone(tz)).date()


def _cents(v, field: str = "amount", allow_zero: bool = False, allow_negative: bool = False) -> int:
    try:
        c = round(float(v) * 100)
    except (TypeError, ValueError) as exc:
        raise PlusError(f"the {field} is a number like 54.99") from exc
    lo = -MAX_CENTS if allow_negative else (0 if allow_zero else 1)
    if not lo <= c <= MAX_CENTS or (allow_negative and c == 0):
        raise PlusError(f"the {field} is out of range")
    return c


def _date(v: str | None, field: str = "date") -> date:
    try:
        return date.fromisoformat(str(v))
    except (TypeError, ValueError) as exc:
        raise PlusError(f"the {field} is YYYY-MM-DD") from exc


def _canon(x: str) -> bool:
    from .mytasks import _canonical
    return _canonical(x)


def _row(conn: Connection, table, org: str, rid: str, what: str):
    r = conn.execute(select(table).where(table.c.id == rid, table.c.organization_id == org)).first() if _canon(rid) else None
    if r is None:
        raise PlusError(f"{what} not found", 404)
    return r


def _changed(conn: Connection, org: str, what: str) -> None:
    emit(conn, "money.changed", org_id=org, payload={"what": what})


# ---------------------------------------------------------------- V6.113 income

def log_income(p: Principal, amount, source: str, day: str | None = None, hours=None, note: str | None = None,
               tz: str | None = "UTC") -> dict:
    src = " ".join((source or "").split())[:60]
    if not src:
        raise PlusError("say where it came from")
    d = _date(day) if day else _today(tz)
    if d > _today(tz) or d < _today(tz) - timedelta(days=800):
        raise PlusError("the day can't be in the future or over two years ago")
    h = None
    if hours not in (None, ""):
        try:
            h = float(hours)
        except (TypeError, ValueError) as exc:
            raise PlusError("hours is a number") from exc
        if not 0 < h <= 24:
            raise PlusError("hours is more than 0 and at most 24")
    iid = db.new_id()
    with transaction() as conn:
        conn.execute(insert(db.income_entries).values(id=iid, organization_id=p.organization_id, amount_cents=_cents(amount),
                                                      source=src, day=d.isoformat(), hours=h, note=(note or "")[:300],
                                                      created_by=p.user_id, created_at=_now().isoformat()))
        _changed(conn, p.organization_id, "income")
    return {"id": iid, "amount": _cents(amount) / 100, "source": src, "day": d.isoformat(), "hours": h}


def remove_income(p: Principal, iid: str) -> None:
    with transaction() as conn:
        _row(conn, db.income_entries, p.organization_id, iid, "entry")
        conn.execute(delete(db.income_entries).where(db.income_entries.c.id == iid))
        _changed(conn, p.organization_id, "income")


def income(conn: Connection, org: str, tz: str | None = "UTC", days: int = 90) -> dict:
    """Your entries, newest first, with this week's and this month's totals, by source, and an hourly rate where you
    logged hours (an average of what you entered, before any costs)."""
    today = _today(tz)
    I = db.income_entries
    since = (today - timedelta(days=max(days, 62))).isoformat()
    rows = conn.execute(select(I).where(I.c.organization_id == org, I.c.day >= since).order_by(I.c.day.desc(), I.c.created_at.desc())).fetchall()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    def total(rs):
        return round(sum(r.amount_cents for r in rs) / 100, 2)

    def rate(rs):
        timed = [r for r in rs if r.hours]
        hrs = sum(r.hours for r in timed)
        return round(sum(r.amount_cents for r in timed) / 100 / hrs, 2) if hrs else None

    week = [r for r in rows if _day(r.day) >= week_start.isoformat()]
    month = [r for r in rows if _day(r.day) >= month_start.isoformat()]
    sources: dict[str, list] = {}
    for r in month:
        sources.setdefault(r.source, []).append(r)
    weeks = []
    for k in range(8):  # the last eight weeks, oldest first
        ws = week_start - timedelta(days=7 * (7 - k))
        we = ws + timedelta(days=7)
        weeks.append({"week_start": ws.isoformat(), "total": total([r for r in rows if ws.isoformat() <= _day(r.day) < we.isoformat()])})
    return {"entries": [{"id": r.id, "amount": r.amount_cents / 100, "source": r.source, "day": _day(r.day), "hours": r.hours,
                         "note": r.note} for r in rows if _day(r.day) >= (today - timedelta(days=days)).isoformat()][:300],
            "week_total": total(week), "month_total": total(month), "week_hourly": rate(week), "month_hourly": rate(month),
            "by_source": sorted(({"source": k, "total": total(v), "hourly": rate(v)} for k, v in sources.items()),
                                key=lambda x: -x["total"]),
            "weeks": weeks}


# ---------------------------------------------------------------- V6.114 paydays

def paydays(s, start: date, count: int = 6) -> list[date]:
    """The next `count` paydays on or after `start` for a schedule, never before its first payday (the anchor)."""
    anchor = s["anchor_day"] if isinstance(s["anchor_day"], date) else date.fromisoformat(_day(s["anchor_day"]))
    if s["cadence"] != "semimonthly":
        start = max(start, anchor)
    out: list[date] = []
    if s["cadence"] in ("weekly", "biweekly"):
        step = 7 if s["cadence"] == "weekly" else 14
        k = (start - anchor).days // step
        d = anchor + timedelta(days=step * k)
        while d < start:
            d += timedelta(days=step)
        while len(out) < count:
            out.append(d)
            d += timedelta(days=step)
        return out
    y, m = start.year, start.month
    while len(out) < count:
        if s["cadence"] == "semimonthly":  # the 15th and the last day of each month
            cands = [date(y, m, 15), date(y, m, _month_len(y, m))]
        else:
            cands = [date(y, m, min(anchor.day, _month_len(y, m)))]
        out += [c for c in cands if c >= start]
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out[:count]


def schedules(conn: Connection, org: str, tz: str | None = "UTC") -> list[dict]:
    S = db.pay_schedules
    today = _today(tz)
    out = []
    for r in conn.execute(select(S).where(S.c.organization_id == org).order_by(S.c.created_at)):
        d = dict(r._mapping)
        d["anchor_day"] = _day(d["anchor_day"])
        d["amount"] = d["amount_cents"] / 100 if d["amount_cents"] is not None else None
        d["next"] = [x.isoformat() for x in paydays(d, today, 6)]
        out.append(d)
    return out


def add_schedule(p: Principal, name: str, cadence: str, anchor_day: str, amount=None) -> dict:
    if cadence not in CADENCES:
        raise PlusError("pay comes weekly, every 2 weeks, twice a month or monthly")
    n = " ".join((name or "").split())[:60] or "Paycheck"
    a = _date(anchor_day, "payday")
    sid = db.new_id()
    with transaction() as conn:
        if len(conn.execute(select(db.pay_schedules.c.id).where(db.pay_schedules.c.organization_id == p.organization_id)).fetchall()) >= 10:
            raise PlusError("up to 10 pay schedules", 409)
        conn.execute(insert(db.pay_schedules).values(id=sid, organization_id=p.organization_id, name=n, cadence=cadence,
                                                     anchor_day=a.isoformat(),
                                                     amount_cents=_cents(amount, allow_zero=True) if amount not in (None, "") else None,
                                                     created_at=_now().isoformat()))
        _changed(conn, p.organization_id, "pay")
    return {"id": sid}


def remove_schedule(p: Principal, sid: str) -> None:
    with transaction() as conn:
        _row(conn, db.pay_schedules, p.organization_id, sid, "pay schedule")
        conn.execute(delete(db.pay_schedules).where(db.pay_schedules.c.id == sid))
        _changed(conn, p.organization_id, "pay")


# ---------------------------------------------------------------- V6.115 the payday planner

def bill_dates(b: dict, start: date, end: date, include_overdue: bool = False) -> list[date]:
    """A bill's due dates from `start` to before `end` that aren't marked paid (plus, if asked, an unpaid past-due one)."""
    paid = {x["period"] for x in b["payments"]}
    out = []
    if include_overdue and b["overdue"]:
        out.append(date.fromisoformat(b["next_due"]))
    if b["cadence"] == "monthly":
        y, m = start.year, start.month
        cands = []
        for _ in range(14):
            cands.append(due_date(b, y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    else:
        cands = [due_date(b, y) for y in (start.year, start.year + 1, start.year + 2)]
    for d in cands:
        if start <= d < end and period_of(b, d) not in paid and d not in out:
            out.append(d)
    return sorted(out)


def paid_dates(b: dict, start: date, end: date) -> list[date]:
    """A bill's due dates from `start` to before `end` that are marked paid."""
    paid = {x["period"] for x in b["payments"]}
    if b["cadence"] == "monthly":
        y, m = start.year, start.month
        cands = []
        for _ in range(3):
            cands.append(due_date(b, y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    else:
        cands = [due_date(b, start.year), due_date(b, start.year + 1)]
    return sorted({d for d in cands if start <= d < end and period_of(b, d) in paid})


def planner(conn: Connection, org: str, tz: str | None = "UTC", periods: int = 4) -> dict:
    """Pay period by pay period: the bills due before the next payday, the cash they need, and what's left of that pay
    (when you've said what a paycheck usually is). With no pay schedule, it groups by the next four weeks."""
    today = _today(tz)
    scheds = schedules(conn, org, tz)
    days: list[tuple[date, int | None, str]] = []
    for s in scheds:
        for d in paydays(s, today - timedelta(days=31), 12):
            days.append((d, s["amount_cents"], s["name"]))
    merged: dict[date, tuple[int | None, list[str]]] = {}  # two schedules paying the same day are one payday
    for d, amt, name in days:
        have, names = merged.get(d, (None, []))
        merged[d] = (amt if have is None else have + amt if amt is not None else have, names + [name])
    days = [(d, amt, " + ".join(dict.fromkeys(n))) for d, (amt, n) in sorted(merged.items())]
    past = [d for d in days if d[0] <= today]
    ahead = [d for d in days if d[0] > today]
    starts = ([past[-1]] if past else [(today, None, "Today")]) + ahead
    if not scheds:
        starts = [(today + timedelta(days=7 * k), None, "Week") for k in range(periods + 1)]
    items = [b for b in bills(conn, org, tz) if b["active"]]
    out = []
    for i in range(min(periods, len(starts) - 1)):
        s, e = starts[i], starts[i + 1]
        due = []
        for b in items:
            for d in bill_dates(b, today if i == 0 else s[0], e[0], include_overdue=i == 0):
                due.append({"bill_id": b["id"], "name": b["name"], "due": d.isoformat(), "amount": b["amount"],
                            "autopay": b["autopay"], "overdue": d < today, "paid": False})
            if i == 0 and scheds:  # bills since this paycheck that you've already paid came out of it too
                for d in paid_dates(b, s[0], today):
                    due.append({"bill_id": b["id"], "name": b["name"], "due": d.isoformat(), "amount": b["amount"],
                                "autopay": b["autopay"], "overdue": False, "paid": True})
        due.sort(key=lambda x: x["due"])
        need = sum(round(x["amount"] * 100) for x in due if x["amount"] is not None)
        pay = s[1]
        out.append({"from": s[0].isoformat(), "to": e[0].isoformat(), "payday": s[2], "pay": pay / 100 if pay is not None else None,
                    "bills": due, "needed": need / 100, "varies": sum(1 for x in due if x["amount"] is None),
                    "left": (pay - need) / 100 if pay is not None else None})
    return {"periods": out, "has_schedule": bool(scheds)}


# ---------------------------------------------------------------- V6.116 savings goals

def goals(conn: Connection, org: str, tz: str | None = "UTC") -> list[dict]:
    G, E = db.savings_goals, db.savings_entries
    today = _today(tz)
    rows = conn.execute(select(G).where(G.c.organization_id == org).order_by(G.c.done, G.c.created_at)).fetchall()
    saved: dict[str, int] = {}
    recent: dict[str, list] = {}
    if rows:
        for e in conn.execute(select(E).where(E.c.organization_id == org, E.c.goal_id.in_([r.id for r in rows]))
                              .order_by(E.c.day.desc(), E.c.created_at.desc())):
            saved[e.goal_id] = saved.get(e.goal_id, 0) + e.amount_cents
            recent.setdefault(e.goal_id, []).append({"id": e.id, "amount": e.amount_cents / 100, "day": _day(e.day)})
    out = []
    for r in rows:
        have = saved.get(r.id, 0)
        left = max(0, r.target_cents - have)
        dl = date.fromisoformat(_day(r.deadline)) if r.deadline else None
        weeks = max(1, -(-(dl - today).days // 7)) if dl and dl > today else None
        out.append({"id": r.id, "name": r.name, "target": r.target_cents / 100, "saved": have / 100, "left": left / 100,
                    "progress": round(max(0.0, min(1.0, have / r.target_cents)), 3), "deadline": _day(r.deadline) if r.deadline else None,
                    "monthly_plan": r.monthly_plan_cents / 100 if r.monthly_plan_cents is not None else None,
                    "per_week_needed": round(left / weeks / 100, 2) if weeks and left else (0.0 if not left else None),
                    "past_deadline": bool(dl and dl < today and left), "done": bool(r.done) or left == 0,
                    "recent": recent.get(r.id, [])[:10]})
    return out


def add_goal(p: Principal, name: str, target, deadline: str | None = None, monthly_plan=None, tz: str | None = "UTC") -> dict:
    n = " ".join((name or "").split())[:60]
    if not n:
        raise PlusError("name the goal")
    t = _cents(target, "target")
    if t < 100:
        raise PlusError("a goal is at least $1")
    dl = _date(deadline, "deadline") if deadline else None
    if dl and dl <= _today(tz):
        raise PlusError("the deadline is after today")
    gid = db.new_id()
    with transaction() as conn:
        if len(conn.execute(select(db.savings_goals.c.id).where(db.savings_goals.c.organization_id == p.organization_id)).fetchall()) >= 20:
            raise PlusError("up to 20 savings goals", 409)
        conn.execute(insert(db.savings_goals).values(id=gid, organization_id=p.organization_id, name=n, target_cents=t,
                                                     deadline=dl.isoformat() if dl else None,
                                                     monthly_plan_cents=_cents(monthly_plan, allow_zero=True) if monthly_plan not in (None, "") else None,
                                                     done=0, created_at=_now().isoformat()))
        _changed(conn, p.organization_id, "savings")
    return {"id": gid}


def save_to(p: Principal, gid: str, amount, day: str | None = None, tz: str | None = "UTC") -> None:
    """Record money you put toward a goal (or took out, as a negative amount). You move the money; this notes it."""
    c = _cents(amount, allow_negative=True)
    d = _date(day) if day else _today(tz)
    if d > _today(tz):
        raise PlusError("the day can't be in the future")
    with transaction() as conn:
        _row(conn, db.savings_goals, p.organization_id, gid, "goal")
        E = db.savings_entries
        have = sum(r.amount_cents for r in conn.execute(select(E.c.amount_cents).where(E.c.goal_id == gid)))
        if have + c < 0:
            raise PlusError(f"that's more than the ${have / 100:.2f} recorded for this goal")
        conn.execute(insert(db.savings_entries).values(id=db.new_id(), goal_id=gid, organization_id=p.organization_id,
                                                       amount_cents=c, day=d.isoformat(), created_at=_now().isoformat()))
        _changed(conn, p.organization_id, "savings")


def remove_goal(p: Principal, gid: str) -> None:
    with transaction() as conn:
        _row(conn, db.savings_goals, p.organization_id, gid, "goal")
        conn.execute(delete(db.savings_entries).where(db.savings_entries.c.goal_id == gid))
        conn.execute(delete(db.savings_goals).where(db.savings_goals.c.id == gid))
        _changed(conn, p.organization_id, "savings")


# ---------------------------------------------------------------- V6.117 the monthly budget

def budget(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """This month: income (what you logged, and what your pay schedules expect for the rest of it), bills, what you plan
    to save, and what that leaves. Every figure comes from what you entered; bills that vary aren't counted in."""
    today = _today(tz)
    first = today.replace(day=1)
    last = today.replace(day=_month_len(today.year, today.month))
    logged = income(conn, org, tz, 40)["month_total"]
    expected = 0
    I = db.income_entries
    logged_rows = [(date.fromisoformat(_day(r.day)), r.amount_cents) for r in conn.execute(
        select(I.c.day, I.c.amount_cents).where(I.c.organization_id == org, I.c.day >= (first - timedelta(days=3)).isoformat()))]
    for s in schedules(conn, org, tz):
        if s["amount_cents"] is None:
            continue
        for d in paydays(s, today + timedelta(days=1), 10):
            if d > last:
                break
            # a paycheck that arrived early (you logged it a few days before) isn't expected again
            if any(d - timedelta(days=4) <= ld <= today and amt >= s["amount_cents"] // 2 for ld, amt in logged_rows):
                continue
            expected += s["amount_cents"]
    bill_total = 0
    varies = 0
    for b in bills(conn, org, tz):
        if b["cadence"] == "yearly" and b["due_month"] != today.month:
            continue
        if not b.get("owed_this_period", True):
            continue
        if b["amount_cents"] is None:
            varies += 1
        else:
            bill_total += b["amount_cents"]
    plan = sum(round((g["monthly_plan"] or 0) * 100) for g in goals(conn, org, tz) if not g["done"])
    inc = round(logged * 100) + expected
    return {"month": first.strftime("%Y-%m"), "income_logged": logged, "income_expected": expected / 100,
            "income": inc / 100, "bills": bill_total / 100, "bills_vary": varies, "savings_plan": plan / 100,
            "left": (inc - bill_total - plan) / 100, "days_left": (last - today).days + 1}


# ---------------------------------------------------------------- V6.118 subscriptions, V6.119 find savings

def set_subscription(p: Principal, bid: str, subscription: bool | None = None, reviewed: bool = False) -> None:
    B, M = db.my_bills, db.bill_meta
    with transaction() as conn:
        _row(conn, B, p.organization_id, bid, "bill")
        have = conn.execute(select(M).where(M.c.bill_id == bid)).first()
        vals = {}
        if subscription is not None:
            vals["subscription"] = int(subscription)
        if reviewed:
            vals["reviewed_at"] = _now().isoformat()
        if have:
            if vals:
                conn.execute(update(M).where(M.c.bill_id == bid).values(**vals))
        else:
            conn.execute(insert(M).values(bill_id=bid, organization_id=p.organization_id, subscription=vals.get("subscription", 0),
                                          reviewed_at=vals.get("reviewed_at")))
        _changed(conn, p.organization_id, "subscriptions")


def subscriptions(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Bills you marked as subscriptions, most expensive per year first, with when you last asked yourself if each
    one is worth it."""
    M = db.bill_meta
    meta = {r.bill_id: r for r in conn.execute(select(M).where(M.c.organization_id == org))}
    out = []
    for b in bills(conn, org, tz):
        m = meta.get(b["id"])
        if not (m and m.subscription):
            continue
        yearly = (b["amount_cents"] or 0) * (12 if b["cadence"] == "monthly" else 1)
        reviewed = m.reviewed_at
        stale = not reviewed or datetime.fromisoformat(str(reviewed).replace("Z", "+00:00")) < _now() - timedelta(days=90)
        out.append({"bill_id": b["id"], "name": b["name"], "amount": b["amount"], "cadence": b["cadence"],
                    "yearly": yearly / 100, "reviewed_at": reviewed, "review_due": stale, "link_url": b["link_url"]})
    out.sort(key=lambda x: -x["yearly"])
    return {"subscriptions": out, "yearly_total": round(sum(x["yearly"] for x in out), 2),
            "flagged": sorted(meta) if meta else []}


def flags(conn: Connection, org: str) -> dict[str, bool]:
    M = db.bill_meta
    return {r.bill_id: bool(r.subscription) for r in conn.execute(select(M).where(M.c.organization_id == org))}


def find_savings(p: Principal, bid: str, tz: str | None = "UTC") -> dict:
    """A research task for the agents to look for a cheaper option. It isn't started: you press Do it (with its
    budget) if you want it, as with any task."""
    from . import mytasks
    with db.get_engine().connect() as conn:
        b = next((x for x in bills(conn, p.organization_id, tz, include_inactive=True) if x["id"] == bid), None) \
            if _canon(bid) else None
    if b is None:
        raise PlusError("bill not found", 404)
    cost = f"${b['amount']:.2f} a {'month' if b['cadence'] == 'monthly' else 'year'}" if b["amount"] is not None else "an amount that varies"
    notes = (f"I pay {cost} for {b['name']}. Compare current options that could cost less for about the same service, "
             "with prices and sources, and say what would change if I switched. Research only: don't sign up for, cancel "
             "or buy anything.")
    return mytasks.create(p, {"title": f"Find a cheaper option than {b['name']}"[:160], "notes": notes, "kind": "research",
                              "list_name": "money"})


# ---------------------------------------------------------------- V6.120 credit-card utilization

def _card_view(r) -> dict:
    u = r.balance_cents / r.limit_cents if r.limit_cents else 0
    return {"id": r.id, "name": r.name, "limit": r.limit_cents / 100, "balance": r.balance_cents / 100,
            "utilization": round(u, 3), "statement_day": r.statement_day, "updated_at": r.updated_at,
            "band": "under 10%" if u < 0.1 else "10–30%" if u <= 0.3 else "over 30%"}


def credit(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Utilization per card and overall, from balances you type in, plus your on-time bill record. General
    information only: it isn't a credit score and doesn't know what any lender will do."""
    C = db.credit_cards
    rows = conn.execute(select(C).where(C.c.organization_id == org).order_by(C.c.name)).fetchall()
    limit = sum(r.limit_cents for r in rows)
    bal = sum(r.balance_cents for r in rows)
    today = _today(tz)
    cards = []
    for r in rows:
        v = _card_view(r)
        if r.statement_day:
            d = date(today.year, today.month, min(r.statement_day, _month_len(today.year, today.month)))
            if d < today:
                y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
                d = date(y, m, min(r.statement_day, _month_len(y, m)))
            v["next_statement"] = d.isoformat()
        cards.append(v)
    overall = bal / limit if limit else None
    return {"cards": cards, "total_limit": limit / 100, "total_balance": bal / 100,
            "utilization": round(overall, 3) if overall is not None else None,
            "record": on_time(conn, org, tz),
            "note": ("Utilization is balance divided by limit. Many lenders and credit bureaus describe keeping it under "
                     "30% (and lower is often better) as a good habit; this is general information, not advice, and not "
                     "a credit score.")}


def save_card(p: Principal, cid: str | None, fields: dict) -> dict:
    C = db.credit_cards
    vals: dict = {}
    if "name" in fields or cid is None:
        n = " ".join(str(fields.get("name") or "").split())[:60]
        if not n:
            raise PlusError("name the card (no card numbers needed)")
        if sum(ch.isdigit() for ch in n) >= 8:
            raise PlusError("leave the card number out; a nickname is enough")
        vals["name"] = n
    if "limit" in fields or cid is None:
        vals["limit_cents"] = _cents(fields.get("limit"), "limit")
        if vals["limit_cents"] < 100:
            raise PlusError("the limit is at least $1")
    if "balance" in fields:
        vals["balance_cents"] = _cents(fields.get("balance") or 0, "balance", allow_zero=True)
    if "statement_day" in fields:
        sd = fields["statement_day"]
        if sd is not None and not (isinstance(sd, int) and 1 <= sd <= 31):
            raise PlusError("the statement day is 1 to 31")
        vals["statement_day"] = sd
    vals["updated_at"] = _now().isoformat()
    with transaction() as conn:
        if cid is None:
            if len(conn.execute(select(C.c.id).where(C.c.organization_id == p.organization_id)).fetchall()) >= 20:
                raise PlusError("up to 20 cards", 409)
            cid = db.new_id()
            conn.execute(insert(C).values(id=cid, organization_id=p.organization_id, balance_cents=vals.pop("balance_cents", 0), **vals))
        else:
            _row(conn, C, p.organization_id, cid, "card")
            conn.execute(update(C).where(C.c.id == cid).values(**vals))
        _changed(conn, p.organization_id, "credit")
        return _card_view(conn.execute(select(C).where(C.c.id == cid)).first())


def remove_card(p: Principal, cid: str) -> None:
    with transaction() as conn:
        _row(conn, db.credit_cards, p.organization_id, cid, "card")
        conn.execute(delete(db.credit_cards).where(db.credit_cards.c.id == cid))
        _changed(conn, p.organization_id, "credit")


# ---------------------------------------------------------------- V6.121 the on-time record

def on_time(conn: Connection, org: str, tz: str | None = "UTC", months: int = 12) -> dict:
    """For each of the last `months` months: each bill's due date there, and whether you marked it paid on or before
    that day (on time), after it (late), or not at all (missed, once the day has passed). Bills count only from the
    month you added them. Based on the dates you recorded; it can't see your bank."""
    zone = _zone(tz)
    today = _today(tz)
    P = db.my_bill_payments
    items = bills(conn, org, tz, include_inactive=True)
    pays: dict[tuple[str, str], str] = {(r.bill_id, r.period): r.paid_at
                                         for r in conn.execute(select(P).where(P.c.organization_id == org))}
    out_months = []
    totals = {"on_time": 0, "late": 0, "missed": 0}
    y, m = today.year, today.month
    seq = []
    for _ in range(months):
        seq.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    for y, m in reversed(seq):
        row = {"month": f"{y:04d}-{m:02d}", "on_time": 0, "late": 0, "missed": 0, "upcoming": 0}
        for b in items:
            if b["cadence"] == "yearly" and b["due_month"] != m:
                continue
            created = datetime.fromisoformat(str(b["created_at"]).replace("Z", "+00:00")).astimezone(zone).date()
            d = due_date(b, y, m) if b["cadence"] == "monthly" else due_date(b, y)
            if d < created:
                continue
            paid_at = pays.get((b["id"], period_of(b, d)))
            if not b["active"] and not paid_at:
                continue  # a bill you've switched off isn't owed (only what you recorded paying counts)
            if paid_at:
                when = datetime.fromisoformat(str(paid_at).replace("Z", "+00:00")).astimezone(zone).date()
                key = "on_time" if when <= d else "late"
            elif d < today:
                key = "missed"
            else:
                key = "upcoming"
            row[key] += 1
            if key in totals:
                totals[key] += 1
        out_months.append(row)
    counted = sum(totals.values())
    return {"months": out_months, **totals, "on_time_rate": round(totals["on_time"] / counted, 3) if counted else None}


# ---------------------------------------------------------------- V6.122 a bill in quick capture

def bill_hint(text: str) -> dict | None:
    """"phone bill $54.99 on the 15th every month" or "car insurance $600 a year due March 1st" looks like a bill:
    offer to add it as one (nothing is saved). Unknown parts are left empty for you to fill in."""
    import re
    months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
    mon_rx = r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
    low = f" {text.lower()} "
    if not re.search(r"\b(bill|rent|mortgage|insurance|subscription|loan|payment|utilities|internet|phone plan)\b", low):
        return None
    amt = re.search(r"\$\s?(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)", low)
    day = re.search(r"\b(?:on the |due (?:on )?(?:the )?)?(3[01]|[12]\d|0?[1-9])(?:st|nd|rd|th)\b", low)
    monthly = re.search(r"\b(every month|monthly|each month|a month|per month)\b|/mo\b", low)
    yearly = re.search(r"\b(every year|yearly|annually|per year|a year)\b", low)
    mon = re.search(mon_rx, low)
    if not (amt or day) or not (monthly or yearly or day):
        return None
    cadence = "yearly" if yearly and not monthly else "monthly"
    due_month = next((i + 1 for i, m in enumerate(months) if m.startswith(mon.group(1)[:3])), None) if mon and cadence == "yearly" else None
    name = re.sub(r"\$\s?\d[\d,]*(?:\.\d{1,2})?|\b(on the |due (on )?(the )?)?(3[01]|[12]\d|0?[1-9])(st|nd|rd|th)\b"
                  r"|\b(every month|monthly|each month|a month|per month|every year|yearly|annually|per year|a year|pay( the)?|my|due|on)\b|/mo\b",
                  " ", text, flags=re.I)
    if cadence == "yearly":
        name = re.sub(mon_rx, " ", name, flags=re.I)
    name = " ".join(name.split()).strip(" ,.-")[:80] or "Bill"
    return {"name": name[:1].upper() + name[1:], "amount": float(amt.group(1).replace(",", "")) if amt else None,
            "due_day": int(day.group(1)) if day else None, "cadence": cadence, "due_month": due_month}


# ---------------------------------------------------------------- V6.123 the money overview

def overview(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    today = _today(tz)
    items = bills(conn, org, tz)
    soon = [b for b in items if b["overdue"] or 0 <= b["days_until"] <= 7]
    inc = income(conn, org, tz, 14)
    g = [x for x in goals(conn, org, tz) if not x["done"]]
    nxt = []
    for s in schedules(conn, org, tz):
        nxt += [d for d in s["next"] if d > today.isoformat()][:1]
    return {"bills_due_soon": [{"id": b["id"], "name": b["name"], "due": b["next_due"], "amount": b["amount"],
                                "overdue": b["overdue"], "autopay": b["autopay"]} for b in soon][:6],
            "bills_due_soon_total": round(sum(b["amount"] or 0 for b in soon), 2),
            "income_this_week": inc["week_total"], "income_this_month": inc["month_total"],
            "next_payday": min(nxt) if nxt else None,
            "savings": [{"name": x["name"], "progress": x["progress"], "saved": x["saved"], "target": x["target"]} for x in g][:3]}
