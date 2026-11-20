"""Money, round 2 (V6.128–V6.157): spending, category budgets, balances you check, safe to spend, debts and payoff
timelines, credit-card paydown targets, a bill calendar, autopay coverage, bill amount changes, late costs, side gigs,
a tax set-aside, an unclaimed-money checklist, a call script, cashback, an emergency-fund meter, net worth, a monthly
review, an on-time streak, split bills and a paycheck split.

Same rules as round 1: everything is worked out from numbers you type in. Nothing is connected to a bank, nothing
moves money, and nothing here is financial, tax or credit advice. Estimates say they are estimates.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.auth import Principal
from services.core.events import transaction

from .money import (_cents, _changed, _date, _row, _today, bill_dates, credit, goals, income, paydays, planner,
                    schedules)
from .taskextra import _day, _month_len, bills, due_date, period_of
from .taskplus import PlusError, _now

DEFAULT_CATEGORIES = ("Groceries", "Eating out", "Gas", "Transport", "Shopping", "Fun", "Health", "Kids", "Pets",
                      "Gifts", "Home", "Other")
ESTIMATE = "An estimate from the numbers you entered, not advice."


def _name(v, what: str, n: int = 60) -> str:
    s = " ".join(str(v or "").split())[:n]
    if not s:
        raise PlusError(f"name the {what}")
    if sum(ch.isdigit() for ch in s) >= 8:
        raise PlusError("leave account and card numbers out; a nickname is enough")
    return s


def _cat(v) -> str:
    s = " ".join(str(v or "").split())[:40]
    if not s:
        raise PlusError("pick a category")
    return s[:1].upper() + s[1:]


def _month_bounds(month: str | None, today: date) -> tuple[date, date]:
    if month:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise PlusError("the month is YYYY-MM")
        y, m = int(month[:4]), int(month[5:])
    else:
        y, m = today.year, today.month
    first = date(y, m, 1)
    return first, date(y, m, _month_len(y, m))


def _monthly_bills_cents(conn: Connection, org: str, tz: str | None) -> int:
    """What your bills come to in an average month (yearly bills spread over 12); bills that vary aren't counted."""
    total = 0
    for b in bills(conn, org, tz):
        if b["amount_cents"] is None:
            continue
        total += b["amount_cents"] if b["cadence"] == "monthly" else round(b["amount_cents"] / 12)
    return total


# ---------------------------------------------------------------- V6.129 spending, V6.130 category budgets

def log_expense(p: Principal, amount, category: str, day: str | None = None, note: str | None = None,
                tz: str | None = "UTC") -> dict:
    d = _date(day) if day else _today(tz)
    if d > _today(tz) or d < _today(tz) - timedelta(days=800):
        raise PlusError("the day can't be in the future or over two years ago")
    eid = db.new_id()
    c = _cents(amount)
    with transaction() as conn:
        conn.execute(insert(db.expenses).values(id=eid, organization_id=p.organization_id, amount_cents=c, category=_cat(category),
                                                day=d.isoformat(), note=(note or "")[:300], created_by=p.user_id,
                                                created_at=_now().isoformat()))
        _changed(conn, p.organization_id, "spending")
    return {"id": eid, "amount": c / 100, "category": _cat(category), "day": d.isoformat()}


def remove_expense(p: Principal, eid: str) -> None:
    with transaction() as conn:
        _row(conn, db.expenses, p.organization_id, eid, "expense")
        conn.execute(delete(db.expenses).where(db.expenses.c.id == eid))
        _changed(conn, p.organization_id, "spending")


def _spent(conn: Connection, org: str, start: date, end: date) -> list:
    E = db.expenses
    return conn.execute(select(E).where(E.c.organization_id == org, E.c.day >= start.isoformat(), E.c.day <= end.isoformat())
                        .order_by(E.c.day.desc(), E.c.created_at.desc())).fetchall()


def spending(conn: Connection, org: str, tz: str | None = "UTC", month: str | None = None) -> dict:
    """A month of what you spent: by category against the limits you set, the entries, and how the month is pacing."""
    today = _today(tz)
    first, last = _month_bounds(month, today)
    rows = _spent(conn, org, first, last)
    B = db.category_budgets
    limits = {r.category: r for r in conn.execute(select(B).where(B.c.organization_id == org))}
    by: dict[str, int] = {}
    for r in rows:
        by[r.category] = by.get(r.category, 0) + r.amount_cents
    cats = []
    for c in sorted(set(by) | set(limits), key=lambda k: -by.get(k, 0)):
        lim = limits[c].limit_cents if c in limits else None
        spent = by.get(c, 0)
        cats.append({"category": c, "spent": spent / 100, "limit": lim / 100 if lim else None,
                     "budget_id": limits[c].id if c in limits else None,
                     "left": (lim - spent) / 100 if lim else None, "over": bool(lim and spent > lim),
                     "progress": round(min(spent / lim, 2.0), 3) if lim else None})
    total = sum(by.values())
    elapsed = (min(today, last) - first).days + 1 if today >= first else 0
    days = (last - first).days + 1
    lim_total = sum(r.limit_cents for r in limits.values())
    return {"month": first.strftime("%Y-%m"), "total": total / 100, "categories": cats,
            "limit_total": lim_total / 100 if limits else None,
            # where you'd land at this pace (only for the current month, after its first few days)
            "pace": round(total / elapsed * days / 100, 2) if first <= today <= last and elapsed >= 5 else None,
            "entries": [{"id": r.id, "amount": r.amount_cents / 100, "category": r.category, "day": _day(r.day), "note": r.note}
                        for r in rows][:300],
            "suggested_categories": list(DEFAULT_CATEGORIES)}


def set_category_budget(p: Principal, category: str, limit) -> dict:
    c = _cat(category)
    B = db.category_budgets
    with transaction() as conn:
        have = conn.execute(select(B).where(B.c.organization_id == p.organization_id, B.c.category == c)).first()
        if limit in (None, "", 0):
            if have:
                conn.execute(delete(B).where(B.c.id == have.id))
        elif have:
            conn.execute(update(B).where(B.c.id == have.id).values(limit_cents=_cents(limit, "limit")))
        else:
            if len(conn.execute(select(B.c.id).where(B.c.organization_id == p.organization_id)).fetchall()) >= 30:
                raise PlusError("up to 30 category limits", 409)
            conn.execute(insert(B).values(id=db.new_id(), organization_id=p.organization_id, category=c,
                                          limit_cents=_cents(limit, "limit")))
        _changed(conn, p.organization_id, "spending")
    return {"category": c}


# ---------------------------------------------------------------- V6.131 balances you check

def accounts(conn: Connection, org: str) -> list[dict]:
    A, Bal = db.cash_accounts, db.cash_balances
    rows = conn.execute(select(A).where(A.c.organization_id == org).order_by(A.c.created_at)).fetchall()
    out = []
    for r in rows:
        hist = conn.execute(select(Bal).where(Bal.c.account_id == r.id).order_by(Bal.c.day.desc(), Bal.c.created_at.desc())
                            .limit(12)).fetchall()
        out.append({"id": r.id, "name": r.name, "kind": r.kind,
                    "balance": hist[0].balance_cents / 100 if hist else None, "as_of": _day(hist[0].day) if hist else None,
                    "history": [{"balance": h.balance_cents / 100, "day": _day(h.day)} for h in hist]})
    return out


def add_account(p: Principal, name: str, kind: str = "checking", balance=None, tz: str | None = "UTC") -> dict:
    if kind not in ("checking", "savings", "cash"):
        raise PlusError("an account is checking, savings or cash")
    n = _name(name, "account")
    aid = db.new_id()
    with transaction() as conn:
        if len(conn.execute(select(db.cash_accounts.c.id).where(db.cash_accounts.c.organization_id == p.organization_id)).fetchall()) >= 15:
            raise PlusError("up to 15 accounts", 409)
        conn.execute(insert(db.cash_accounts).values(id=aid, organization_id=p.organization_id, name=n, kind=kind,
                                                     created_at=_now().isoformat()))
        if balance not in (None, ""):
            _put_balance(conn, p.organization_id, aid, balance, _today(tz))
        _changed(conn, p.organization_id, "accounts")
    return {"id": aid}


def _put_balance(conn: Connection, org: str, aid: str, balance, d: date) -> None:
    c = round(float(balance) * 100) if isinstance(balance, (int, float)) else None
    if c is None:
        try:
            c = round(float(balance) * 100)
        except (TypeError, ValueError) as exc:
            raise PlusError("the balance is a number like 1250.00") from exc
    if not -100_000_000 <= c <= 100_000_000:
        raise PlusError("the balance is out of range")
    Bal = db.cash_balances
    conn.execute(delete(Bal).where(Bal.c.account_id == aid, Bal.c.day == d.isoformat()))  # one check-in a day
    conn.execute(insert(Bal).values(id=db.new_id(), account_id=aid, organization_id=org, balance_cents=c, day=d.isoformat(),
                                    created_at=_now().isoformat()))


def check_in(p: Principal, aid: str, balance, day: str | None = None, tz: str | None = "UTC") -> None:
    d = _date(day) if day else _today(tz)
    if d > _today(tz):
        raise PlusError("the day can't be in the future")
    with transaction() as conn:
        _row(conn, db.cash_accounts, p.organization_id, aid, "account")
        _put_balance(conn, p.organization_id, aid, balance, d)
        _changed(conn, p.organization_id, "accounts")


def remove_account(p: Principal, aid: str) -> None:
    with transaction() as conn:
        _row(conn, db.cash_accounts, p.organization_id, aid, "account")
        conn.execute(delete(db.cash_balances).where(db.cash_balances.c.account_id == aid))
        conn.execute(update(db.bill_extras).where(db.bill_extras.c.autopay_account_id == aid).values(autopay_account_id=None))
        conn.execute(delete(db.cash_accounts).where(db.cash_accounts.c.id == aid))
        _changed(conn, p.organization_id, "accounts")


# ---------------------------------------------------------------- V6.132 safe to spend, V6.133 low-balance warning

def _next_payday(conn: Connection, org: str, tz: str | None) -> date | None:
    today = _today(tz)
    days = [d for s in schedules(conn, org, tz) for d in paydays(s, today + timedelta(days=1), 1)]
    return min(days) if days else None


def safe_to_spend(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Spending money per day until your next payday: the checking and cash balances you last entered, less what you
    logged spending since then, less unpaid bills due before payday, less what you plan to save before then.

    With no payday set, it runs to the end of the month. An estimate, not advice; it's only as current as your last
    balance check-in."""
    today = _today(tz)
    accts = [a for a in accounts(conn, org) if a["kind"] in ("checking", "cash")]
    have = [a for a in accts if a["balance"] is not None]
    nxt = _next_payday(conn, org, tz)
    until = nxt or today.replace(day=_month_len(today.year, today.month)) + timedelta(days=1)
    out = {"next_payday": nxt.isoformat() if nxt else None, "until": until.isoformat(), "days": max(1, (until - today).days),
           "accounts": [{"name": a["name"], "balance": a["balance"], "as_of": a["as_of"]} for a in accts], "note": ESTIMATE}
    if not have:
        return {**out, "ready": False, "reason": "Add a checking account and its balance to see this."}
    bal = sum(round(a["balance"] * 100) for a in have)
    oldest = min(date.fromisoformat(a["as_of"]) for a in have)
    since = sum(r.amount_cents for r in _spent(conn, org, oldest + timedelta(days=1), today))
    due = []
    for b in bills(conn, org, tz):
        for d in bill_dates(b, today, until, include_overdue=True):
            due.append({"bill_id": b["id"], "name": b["name"], "due": d.isoformat(), "amount": b["amount"], "autopay": b["autopay"],
                        "overdue": d < today})
    bills_c = sum(round(x["amount"] * 100) for x in due if x["amount"] is not None)
    # monthly savings plans, spread over the days to payday
    plan_m = sum(round((g["monthly_plan"] or 0) * 100) for g in goals(conn, org, tz) if not g["done"])
    save_c = round(plan_m * min(out["days"], 31) / 30)
    left = bal - since - bills_c - save_c
    stale = (today - oldest).days
    return {**out, "ready": True, "balance": bal / 100, "spent_since": since / 100, "bills_before_payday": due,
            "bills_total": bills_c / 100, "bills_vary": sum(1 for x in due if x["amount"] is None), "savings_set_aside": save_c / 100,
            "left": left / 100, "per_day": round(max(0, left) / out["days"] / 100, 2), "balance_age_days": stale,
            "short": left < 0, "shortfall": round(-left / 100, 2) if left < 0 else 0.0,
            "warning": (f"Your bills before payday come to ${bills_c / 100:,.2f}, more than the ${(bal - since) / 100:,.2f} you have. "
                        "Consider calling the biller about a due date or a payment arrangement before it's late.")
            if bills_c > bal - since else None}


# ---------------------------------------------------------------- V6.134–V6.137 debts, payoff, interest

def debt_list(conn: Connection, org: str) -> list[dict]:
    D = db.debts
    out = []
    for r in conn.execute(select(D).where(D.c.organization_id == org).order_by(D.c.name)):
        out.append({"id": r.id, "name": r.name, "kind": r.kind, "balance": r.balance_cents / 100, "apr": r.apr,
                    "min_payment": r.min_payment_cents / 100, "card_id": r.card_id, "updated_at": r.updated_at,
                    "monthly_interest": round(r.balance_cents * r.apr / 1200 / 100, 2),
                    "min_covers_interest": r.min_payment_cents > r.balance_cents * r.apr / 1200 or r.balance_cents == 0})
    return out


def save_debt(p: Principal, did: str | None, fields: dict) -> dict:
    D = db.debts
    vals: dict = {}
    if "name" in fields or did is None:
        vals["name"] = _name(fields.get("name"), "debt")
    if "kind" in fields:
        if fields["kind"] not in ("card", "loan", "other"):
            raise PlusError("a debt is a card, a loan or other")
        vals["kind"] = fields["kind"]
    if "balance" in fields or did is None:
        vals["balance_cents"] = _cents(fields.get("balance") or 0, "balance", allow_zero=True)
    if "apr" in fields or did is None:
        try:
            apr = float(fields.get("apr") or 0)
        except (TypeError, ValueError) as exc:
            raise PlusError("the APR is a percent like 24.99") from exc
        if not 0 <= apr <= 100:
            raise PlusError("the APR is 0 to 100 percent")
        vals["apr"] = round(apr, 3)
    if "min_payment" in fields or did is None:
        vals["min_payment_cents"] = _cents(fields.get("min_payment") or 0, "minimum payment", allow_zero=True)
    vals["updated_at"] = _now().isoformat()
    with transaction() as conn:
        if "card_id" in fields:
            cid = fields["card_id"]
            if cid:
                _row(conn, db.credit_cards, p.organization_id, cid, "card")
            vals["card_id"] = cid or None
        if did is None:
            if len(conn.execute(select(D.c.id).where(D.c.organization_id == p.organization_id)).fetchall()) >= 25:
                raise PlusError("up to 25 debts", 409)
            did = db.new_id()
            conn.execute(insert(D).values(id=did, organization_id=p.organization_id, kind=vals.pop("kind", "card"), **vals))
        else:
            _row(conn, D, p.organization_id, did, "debt")
            conn.execute(update(D).where(D.c.id == did).values(**vals))
        _changed(conn, p.organization_id, "debts")
    return {"id": did}


def remove_debt(p: Principal, did: str) -> None:
    with transaction() as conn:
        _row(conn, db.debts, p.organization_id, did, "debt")
        conn.execute(delete(db.debts).where(db.debts.c.id == did))
        _changed(conn, p.organization_id, "debts")


def simulate(debts: list[dict], extra_cents: int, method: str, start: date, cap_months: int = 600) -> dict:
    """Month by month: interest accrues (APR / 12), every debt gets its minimum, and the extra (plus the minimums of
    debts already paid off) goes to the target: the highest APR first (avalanche) or the smallest balance first
    (snowball). Returns when each is paid off and the interest along the way. Simple monthly interest; real
    statements compound daily, so treat this as an estimate."""
    bal = {d["id"]: round(d["balance"] * 100) for d in debts}
    info = {d["id"]: d for d in debts}
    done: dict[str, int] = {k: 0 for k, v in bal.items() if v <= 0}
    interest = 0
    month = 0
    budget = sum(round(d["min_payment"] * 100) for d in debts) + max(0, extra_cents)
    while any(v > 0 for v in bal.values()) and month < cap_months:
        month += 1
        for k in bal:
            if bal[k] > 0:
                i = round(bal[k] * info[k]["apr"] / 1200)
                bal[k] += i
                interest += i
        pool = budget
        for k in bal:  # minimums first
            if bal[k] > 0:
                pay = min(bal[k], round(info[k]["min_payment"] * 100), pool)
                bal[k] -= pay
                pool -= pay
        order = sorted((k for k in bal if bal[k] > 0),
                       key=(lambda k: (-info[k]["apr"], bal[k])) if method == "avalanche" else (lambda k: (bal[k], -info[k]["apr"])))
        for k in order:
            if pool <= 0:
                break
            pay = min(bal[k], pool)
            bal[k] -= pay
            pool -= pay
        for k in bal:
            if bal[k] <= 0 and k not in done:
                done[k] = month
    finished = all(v <= 0 for v in bal.values())

    def when(m: int) -> str:
        y, mo = start.year, start.month + m
        y += (mo - 1) // 12
        mo = (mo - 1) % 12 + 1
        return f"{y:04d}-{mo:02d}"

    return {"method": method, "months": month if finished else None, "finishes": when(month) if finished else None,
            "interest": interest / 100 if finished else None, "monthly_payment": budget / 100,
            "order": [{"id": k, "name": info[k]["name"], "paid_off_month": done.get(k), "paid_off": when(done[k]) if k in done else None}
                      for k in sorted(done, key=lambda k: (done[k], info[k]["name"]))]
            + [{"id": k, "name": info[k]["name"], "paid_off_month": None, "paid_off": None} for k in bal if k not in done],
            "never": not finished}


def payoff(conn: Connection, org: str, tz: str | None = "UTC", extra: float = 0) -> dict:
    """Snowball and avalanche side by side at your minimums plus `extra` a month, and the minimums alone for
    comparison (V6.135, V6.136). Which to use is your call: avalanche usually costs less interest, snowball clears
    accounts sooner. An estimate, not advice."""
    if not 0 <= extra <= 1_000_000:
        raise PlusError("the extra is 0 to 1,000,000")
    ds = [d for d in debt_list(conn, org) if d["balance"] > 0]
    start = _today(tz)
    if not ds:
        return {"debts": 0, "note": ESTIMATE}
    ex = round(extra * 100)
    base = simulate(ds, 0, "avalanche", start)
    ava = simulate(ds, ex, "avalanche", start)
    sno = simulate(ds, ex, "snowball", start)
    saved = round(base["interest"] - ava["interest"], 2) if base["interest"] is not None and ava["interest"] is not None else None
    return {"debts": len(ds), "total": round(sum(d["balance"] for d in ds), 2), "extra": extra,
            "minimums_only": base, "avalanche": ava, "snowball": sno,
            "interest_saved_by_extra": saved,
            "months_saved_by_extra": base["months"] - ava["months"] if base["months"] and ava["months"] else None,
            "not_covering_interest": [d["name"] for d in ds if not d["min_covers_interest"]],
            "note": ("Simple monthly interest from the APRs you entered; real statements compound daily and minimums change "
                     "as balances fall. " + ESTIMATE)}


# ---------------------------------------------------------------- V6.138 paydown targets, V6.139 before the statement

def paydown(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """For each card: what it would take to bring the balance under 30% and under 10% of the limit, before the next
    statement closes (which is often the balance that gets reported). Plain arithmetic, general information only."""
    c = credit(conn, org, tz)
    debts = {d["card_id"]: d for d in debt_list(conn, org) if d["card_id"]}
    out = []
    for card in c["cards"]:
        lim, bal = round(card["limit"] * 100), round(card["balance"] * 100)
        to30 = max(0, bal - lim * 30 // 100)
        to10 = max(0, bal - lim * 10 // 100)
        d = debts.get(card["id"])
        out.append({"id": card["id"], "name": card["name"], "balance": card["balance"], "limit": card["limit"],
                    "utilization": card["utilization"], "pay_to_30": to30 / 100, "pay_to_10": to10 / 100,
                    "next_statement": card.get("next_statement"),
                    "monthly_interest": d["monthly_interest"] if d else None, "apr": d["apr"] if d else None})
    total_lim = round(c["total_limit"] * 100)
    total_bal = round(c["total_balance"] * 100)
    return {"cards": out, "overall_to_30": max(0, total_bal - total_lim * 30 // 100) / 100,
            "overall_to_10": max(0, total_bal - total_lim * 10 // 100) / 100, "utilization": c["utilization"],
            "note": ("Card issuers usually report the balance on your statement. Paying it down before the statement "
                     "closes can lower the utilization that's reported. General information, not advice, and not a score.")}


# ---------------------------------------------------------------- V6.140 calendar feed

def _ics_text(s: str) -> str:
    return re.sub(r"([,;\\])", r"\\\1", s.replace("\n", " "))[:120]


def calendar_ics(conn: Connection, org: str, tz: str | None = "UTC", months: int = 12) -> str:
    """Bills (unpaid due dates) and paydays for the next `months` months as all-day events, to add to a calendar."""
    today = _today(tz)
    end = today + timedelta(days=31 * months)
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    ev = []
    for b in bills(conn, org, tz):
        amt = f" ${b['amount']:,.2f}" if b["amount"] is not None else ""
        for d in bill_dates(b, today, end):
            ev.append((d, f"bill-{b['id']}-{d.isoformat()}", f"Due: {b['name']}{amt}", "Bill marked paid in the app won't update this file."))
    for s in schedules(conn, org, tz):
        for d in paydays(s, today, 60):
            if d >= end:
                break
            ev.append((d, f"pay-{s['id']}-{d.isoformat()}", f"Payday: {s['name']}", ""))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AICiv//Money//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:Bills and paydays"]
    for d, uid, title, desc in sorted(ev):
        lines += ["BEGIN:VEVENT", f"UID:{uid}@aiciv", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                  f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}", f"SUMMARY:{_ics_text(title)}"]
        if desc:
            lines.append(f"DESCRIPTION:{_ics_text(desc)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------- V6.141 autopay, V6.142 amount changes, V6.143 late cost

def extras(conn: Connection, org: str) -> dict[str, dict]:
    X = db.bill_extras
    return {r.bill_id: {"autopay_account_id": r.autopay_account_id,
                        "late_fee": r.late_fee_cents / 100 if r.late_fee_cents is not None else None, "grace_days": r.grace_days}
            for r in conn.execute(select(X).where(X.c.organization_id == org))}


def set_extras(p: Principal, bid: str, fields: dict) -> None:
    X = db.bill_extras
    vals: dict = {}
    if "late_fee" in fields:
        vals["late_fee_cents"] = _cents(fields["late_fee"], "late fee", allow_zero=True) if fields["late_fee"] not in (None, "") else None
    if "grace_days" in fields:
        g = fields["grace_days"]
        if g is not None and not (isinstance(g, int) and 0 <= g <= 60):
            raise PlusError("grace days is 0 to 60")
        vals["grace_days"] = g
    with transaction() as conn:
        _row(conn, db.my_bills, p.organization_id, bid, "bill")
        if "autopay_account_id" in fields:
            aid = fields["autopay_account_id"]
            if aid:
                _row(conn, db.cash_accounts, p.organization_id, aid, "account")
            vals["autopay_account_id"] = aid or None
        if conn.execute(select(X.c.bill_id).where(X.c.bill_id == bid)).first():
            if vals:
                conn.execute(update(X).where(X.c.bill_id == bid).values(**vals))
        else:
            conn.execute(insert(X).values(bill_id=bid, organization_id=p.organization_id, **vals))
        _changed(conn, p.organization_id, "bills")


def bill_checks(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Three checks on your bills:
    - autopay coverage: autopay bills due before your next payday, against the balance of the account each is paid
      from (or all your checking if you didn't say), so a payment doesn't bounce;
    - amount changes: the last amount you recorded paying vs the one before it (or the bill's usual amount), when it
      moved by 10% or more;
    - late cost: for an overdue bill with a late fee you entered, what being late costs and when the grace days end."""
    today = _today(tz)
    items = bills(conn, org, tz)
    ex = extras(conn, org)
    accts = {a["id"]: a for a in accounts(conn, org)}
    nxt = _next_payday(conn, org, tz) or today + timedelta(days=14)
    per_acct: dict[str | None, list] = {}
    for b in items:
        if not b["autopay"]:
            continue
        for d in bill_dates(b, today, nxt):
            per_acct.setdefault(ex.get(b["id"], {}).get("autopay_account_id"), []).append(
                {"bill_id": b["id"], "name": b["name"], "due": d.isoformat(), "amount": b["amount"]})
    cover = []
    checking = [a for a in accts.values() if a["kind"] in ("checking", "cash") and a["balance"] is not None]
    for aid, due in per_acct.items():
        need = sum(round(x["amount"] * 100) for x in due if x["amount"] is not None)
        if aid and aid in accts:
            name, bal = accts[aid]["name"], accts[aid]["balance"]
        else:
            name, bal = "Your checking", round(sum(a["balance"] for a in checking), 2) if checking else None
        cover.append({"account_id": aid, "account": name, "balance": bal, "bills": due, "needed": need / 100,
                      "covered": None if bal is None else round(bal * 100) >= need,
                      "short_by": round(max(0, need - round(bal * 100)) / 100, 2) if bal is not None else None})
    changes = []
    for b in items:
        amts = [x["amount_cents"] for x in b["payments"] if x["amount_cents"]]
        if not amts:
            continue
        last = amts[0]
        before = amts[1] if len(amts) > 1 else b["amount_cents"]
        if before and abs(last - before) * 10 >= before:
            changes.append({"bill_id": b["id"], "name": b["name"], "last": last / 100, "before": before / 100,
                            "change": round((last - before) / before, 3), "period": b["payments"][0]["period"]})
    late = []
    for b in items:
        e = ex.get(b["id"], {})
        if not b["overdue"]:
            continue
        due = date.fromisoformat(b["next_due"])
        grace = e.get("grace_days") or 0
        late.append({"bill_id": b["id"], "name": b["name"], "due": b["next_due"], "late_fee": e.get("late_fee"),
                     "grace_ends": (due + timedelta(days=grace)).isoformat(), "in_grace": today <= due + timedelta(days=grace),
                     "days_late": (today - due).days})
    return {"next_payday": nxt.isoformat(), "autopay": cover, "amount_changes": changes, "late": late,
            "late_fees_at_risk": round(sum(x["late_fee"] or 0 for x in late), 2), "extras": ex}


# ---------------------------------------------------------------- V6.144 side gigs, V6.145 tax set-aside

def settings(conn: Connection, org: str) -> dict:
    S = db.money_settings
    r = conn.execute(select(S).where(S.c.organization_id == org)).first()
    return {"mileage_rate": r.mileage_rate_cents / 100 if r and r.mileage_rate_cents is not None else None,
            "tax_pct": r.tax_pct if r else None, "emergency_goal_id": r.emergency_goal_id if r else None,
            "gig_sources": [x for x in (r.gig_sources or "").split("\n") if x] if r else []}


def save_settings(p: Principal, fields: dict) -> dict:
    S = db.money_settings
    vals: dict = {}
    if "mileage_rate" in fields:
        v = fields["mileage_rate"]
        vals["mileage_rate_cents"] = None if v in (None, "") else _cents(v, "mileage rate", allow_zero=True)
        if vals["mileage_rate_cents"] is not None and vals["mileage_rate_cents"] > 1000:
            raise PlusError("the mileage rate is up to $10 a mile")
    if "tax_pct" in fields:
        v = fields["tax_pct"]
        if v is not None and not (isinstance(v, (int, float)) and 0 <= v <= 60):
            raise PlusError("set aside 0 to 60 percent")
        vals["tax_pct"] = v
    if "gig_sources" in fields:
        srcs = list(dict.fromkeys(" ".join(str(x).split())[:60] for x in (fields["gig_sources"] or []) if str(x).strip()))
        if len(srcs) > 20:
            raise PlusError("up to 20 side gigs")
        vals["gig_sources"] = "\n".join(srcs)
    with transaction() as conn:
        if "emergency_goal_id" in fields:
            gid = fields["emergency_goal_id"]
            if gid:
                _row(conn, db.savings_goals, p.organization_id, gid, "goal")
            vals["emergency_goal_id"] = gid or None
        if conn.execute(select(S.c.organization_id).where(S.c.organization_id == p.organization_id)).first():
            if vals:
                conn.execute(update(S).where(S.c.organization_id == p.organization_id).values(**vals))
        else:
            conn.execute(insert(S).values(organization_id=p.organization_id, **{"gig_sources": "", **vals}))
        _changed(conn, p.organization_id, "settings")
        return settings(conn, p.organization_id)


def log_gig_cost(p: Principal, source: str, amount=None, miles=None, day: str | None = None, note: str | None = None,
                 tz: str | None = "UTC") -> dict:
    src = _name(source, "gig")
    c = _cents(amount, "cost", allow_zero=True) if amount not in (None, "") else 0
    try:
        mi = float(miles or 0)
    except (TypeError, ValueError) as exc:
        raise PlusError("miles is a number") from exc
    if not 0 <= mi <= 2000:
        raise PlusError("miles is 0 to 2,000")
    if not c and not mi:
        raise PlusError("enter a cost or miles")
    d = _date(day) if day else _today(tz)
    if d > _today(tz):
        raise PlusError("the day can't be in the future")
    cid = db.new_id()
    with transaction() as conn:
        conn.execute(insert(db.gig_costs).values(id=cid, organization_id=p.organization_id, source=src, day=d.isoformat(),
                                                 amount_cents=c, miles=round(mi, 1), note=(note or "")[:300],
                                                 created_at=_now().isoformat()))
        _changed(conn, p.organization_id, "gigs")
    return {"id": cid}


def remove_gig_cost(p: Principal, cid: str) -> None:
    with transaction() as conn:
        _row(conn, db.gig_costs, p.organization_id, cid, "cost")
        conn.execute(delete(db.gig_costs).where(db.gig_costs.c.id == cid))
        _changed(conn, p.organization_id, "gigs")


def gigs(conn: Connection, org: str, tz: str | None = "UTC", days: int = 30) -> dict:
    """Each side gig over the last `days` days and this year: what it paid, your costs, miles at the rate you set,
    and the hourly that leaves (when you logged hours). Then a tax set-aside: your percent of this year's gig profit.
    Not tax advice: what you actually owe depends on your whole situation."""
    today = _today(tz)
    st = settings(conn, org)
    rate = round((st["mileage_rate"] or 0) * 100)
    I, G = db.income_entries, db.gig_costs
    year0 = date(today.year, 1, 1)
    since = min(year0, today - timedelta(days=days))
    inc = conn.execute(select(I).where(I.c.organization_id == org, I.c.day >= since.isoformat())).fetchall()
    costs = conn.execute(select(G).where(G.c.organization_id == org, G.c.day >= since.isoformat())
                         .order_by(G.c.day.desc(), G.c.created_at.desc())).fetchall()
    names = list(dict.fromkeys(st["gig_sources"] + sorted({c.source for c in costs})))
    win = (today - timedelta(days=days)).isoformat()

    def figures(src: str, start: str) -> dict:
        rows = [r for r in inc if r.source.lower() == src.lower() and _day(r.day) >= start]
        cs = [c for c in costs if c.source.lower() == src.lower() and _day(c.day) >= start]
        earned = sum(r.amount_cents for r in rows)
        spent = sum(c.amount_cents for c in cs)
        miles = sum(c.miles for c in cs)
        mileage = round(miles * rate)
        hours = sum(r.hours or 0 for r in rows)
        net = earned - spent - mileage
        return {"earned": earned / 100, "costs": spent / 100, "miles": round(miles, 1), "mileage": mileage / 100,
                "net": net / 100, "hours": round(hours, 2),
                "hourly_gross": round(earned / hours / 100, 2) if hours else None,
                "hourly_net": round(net / hours / 100, 2) if hours else None}

    out = [{"source": n, "recent": figures(n, win), "year": figures(n, year0.isoformat())} for n in names]
    profit = sum(max(0, round(x["year"]["net"] * 100)) for x in out)
    pct = st["tax_pct"]
    return {"gigs": out, "days": days, "mileage_rate": st["mileage_rate"], "tax_pct": pct,
            "year_profit": profit / 100, "tax_set_aside": round(profit * pct / 100 / 100, 2) if pct is not None else None,
            "costs": [{"id": c.id, "source": c.source, "day": _day(c.day), "amount": c.amount_cents / 100, "miles": c.miles,
                       "note": c.note} for c in costs if _day(c.day) >= win][:200],
            "note": ("Miles are counted at the rate you set; check the current IRS standard mileage rate yourself. The "
                     "set-aside is your percent of this year's gig profit, not a tax calculation or tax advice.")}


# ---------------------------------------------------------------- V6.146 unclaimed money checklist

CHECKLIST = (
    {"key": "state_unclaimed", "title": "Search unclaimed property in every state you've lived in",
     "detail": "Old paychecks, deposits, refunds and accounts end up with the state. Searching and claiming is free.",
     "url": "https://www.missingmoney.com"},
    {"key": "naupa", "title": "Find your state's official unclaimed property office",
     "detail": "From the association of state unclaimed property programs.", "url": "https://unclaimed.org"},
    {"key": "irs_refund", "title": "Check for a federal tax refund you didn't get",
     "detail": "The IRS refund tracker.", "url": "https://www.irs.gov/wheres-my-refund"},
    {"key": "retirement", "title": "Look for a forgotten 401(k) or pension",
     "detail": "The U.S. Department of Labor's Retirement Savings Lost and Found.", "url": "https://lostandfound.dol.gov"},
    {"key": "savings_bonds", "title": "Look for matured savings bonds",
     "detail": "Treasury Hunt, from the U.S. Treasury.", "url": "https://paymentintegrity.treasury.gov/savings-bonds/treasury-hunt"},
    {"key": "never_pay", "title": "Never pay a finder's fee to claim",
     "detail": "Official searches are free. Ignore messages that ask for a fee or your bank login to release money.",
     "url": None},
)


def checklist(conn: Connection, org: str) -> dict:
    M = db.money_checks
    done = {r.key: r.done_at for r in conn.execute(select(M).where(M.c.organization_id == org))}
    return {"items": [{**i, "done_at": done.get(i["key"])} for i in CHECKLIST],
            "note": "These are official, free searches. You do them yourself; the app doesn't search or claim anything."}


def check_item(p: Principal, key: str, done: bool) -> None:
    if key not in {i["key"] for i in CHECKLIST}:
        raise PlusError("not on the checklist", 404)
    M = db.money_checks
    with transaction() as conn:
        conn.execute(delete(M).where(M.c.organization_id == p.organization_id, M.c.key == key))
        if done:
            conn.execute(insert(M).values(organization_id=p.organization_id, key=key, done_at=_now().isoformat()))
        _changed(conn, p.organization_id, "checklist")


# ---------------------------------------------------------------- V6.147 a call script to lower a bill

def call_script(conn: Connection, org: str, bid: str, tz: str | None = "UTC", years: int | None = None,
                competitor_price: float | None = None) -> dict:
    """A short script to ask a provider for a lower rate, filled from the bill. You make the call; nothing is sent."""
    from .money import _canon
    b = next((x for x in bills(conn, org, tz, include_inactive=True) if x["id"] == bid), None) if _canon(bid) else None
    if b is None:
        raise PlusError("bill not found", 404)
    per = "month" if b["cadence"] == "monthly" else "year"
    amt = f"${b['amount']:,.2f} a {per}" if b["amount"] is not None else "my current rate"
    tenure = f"I've been a customer for {years} year{'s' if years != 1 else ''}" if years else "I've been a customer for a while"
    comp = f" I've seen offers around ${competitor_price:,.2f} a {per} for similar service." if competitor_price else ""
    lines = [
        f"Hi, I'm calling about my {b['name']} account. {tenure}, and I'm currently paying {amt}.{comp}",
        "I'd like to keep my service, but I need to lower my bill. What promotions, loyalty discounts or lower plans "
        "can you offer me?",
        "If they can't help: \"Could you transfer me to the retention or loyalty department?\"",
        "Before agreeing: ask for the new monthly price, how long it lasts, any contract or fees, and a confirmation "
        "number. Write them down.",
        "If nothing works: \"Thanks. I'll think about my options.\" You don't have to decide on the call.",
    ]
    return {"bill_id": b["id"], "name": b["name"], "lines": lines,
            "note": "A starting point to edit. You make the call; the app doesn't contact anyone."}


# ---------------------------------------------------------------- V6.148 cashback

def log_cashback(p: Principal, card: str, amount, day: str | None = None, tz: str | None = "UTC") -> dict:
    n = _name(card, "card")
    d = _date(day) if day else _today(tz)
    if d > _today(tz):
        raise PlusError("the day can't be in the future")
    cid = db.new_id()
    with transaction() as conn:
        conn.execute(insert(db.cashback_entries).values(id=cid, organization_id=p.organization_id, card=n,
                                                        amount_cents=_cents(amount), day=d.isoformat(),
                                                        created_at=_now().isoformat()))
        _changed(conn, p.organization_id, "cashback")
    return {"id": cid}


def remove_cashback(p: Principal, cid: str) -> None:
    with transaction() as conn:
        _row(conn, db.cashback_entries, p.organization_id, cid, "entry")
        conn.execute(delete(db.cashback_entries).where(db.cashback_entries.c.id == cid))
        _changed(conn, p.organization_id, "cashback")


def cashback(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    today = _today(tz)
    C = db.cashback_entries
    rows = conn.execute(select(C).where(C.c.organization_id == org, C.c.day >= date(today.year - 1, 1, 1).isoformat())
                        .order_by(C.c.day.desc(), C.c.created_at.desc())).fetchall()
    y0 = date(today.year, 1, 1).isoformat()
    by: dict[str, int] = {}
    for r in rows:
        if _day(r.day) >= y0:
            by[r.card] = by.get(r.card, 0) + r.amount_cents
    return {"year": today.year, "year_total": sum(by.values()) / 100,
            "by_card": sorted(({"card": k, "total": v / 100} for k, v in by.items()), key=lambda x: -x["total"]),
            "entries": [{"id": r.id, "card": r.card, "amount": r.amount_cents / 100, "day": _day(r.day)} for r in rows][:200]}


# ---------------------------------------------------------------- V6.149 emergency fund

def emergency(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """How many months of bills (plus your average spending over the last 90 days) the goal you picked as your
    emergency fund would cover. Many guides suggest three to six months; general information only."""
    st = settings(conn, org)
    today = _today(tz)
    g = next((x for x in goals(conn, org, tz) if x["id"] == st["emergency_goal_id"]), None)
    bills_m = _monthly_bills_cents(conn, org, tz)
    spent = sum(r.amount_cents for r in _spent(conn, org, today - timedelta(days=89), today))
    spend_m = round(spent / 3)
    need = bills_m + spend_m
    saved = round(g["saved"] * 100) if g else 0
    return {"goal_id": g["id"] if g else None, "goal": g["name"] if g else None, "saved": saved / 100,
            "monthly_bills": bills_m / 100, "monthly_spending": spend_m / 100, "monthly_need": need / 100,
            "months_covered": round(saved / need, 1) if need and g else None,
            "for_3_months": max(0, 3 * need - saved) / 100 if need else None,
            "for_6_months": max(0, 6 * need - saved) / 100 if need else None,
            "note": "Many guides suggest three to six months of expenses. General information, not advice."}


# ---------------------------------------------------------------- V6.150 net worth

def save_asset(p: Principal, aid: str | None, name: str, value) -> dict:
    A = db.assets
    n = _name(name, "asset")
    v = _cents(value, "value", allow_zero=True)
    with transaction() as conn:
        if aid is None:
            if len(conn.execute(select(A.c.id).where(A.c.organization_id == p.organization_id)).fetchall()) >= 30:
                raise PlusError("up to 30 assets", 409)
            aid = db.new_id()
            conn.execute(insert(A).values(id=aid, organization_id=p.organization_id, name=n, value_cents=v, updated_at=_now().isoformat()))
        else:
            _row(conn, A, p.organization_id, aid, "asset")
            conn.execute(update(A).where(A.c.id == aid).values(name=n, value_cents=v, updated_at=_now().isoformat()))
        _changed(conn, p.organization_id, "net_worth")
    return {"id": aid}


def remove_asset(p: Principal, aid: str) -> None:
    with transaction() as conn:
        _row(conn, db.assets, p.organization_id, aid, "asset")
        conn.execute(delete(db.assets).where(db.assets.c.id == aid))
        _changed(conn, p.organization_id, "net_worth")


def _totals(conn: Connection, org: str, tz: str | None) -> tuple[int, int, list, list]:
    A = db.assets
    have = []
    for a in accounts(conn, org):
        if a["balance"] is not None:
            have.append({"name": a["name"], "value": a["balance"], "kind": "account"})
    for r in conn.execute(select(A).where(A.c.organization_id == org).order_by(A.c.name)):
        have.append({"id": r.id, "name": r.name, "value": r.value_cents / 100, "kind": "asset"})
    owe = [{"name": d["name"], "value": d["balance"], "kind": "debt"} for d in debt_list(conn, org)]
    linked = {d["card_id"] for d in debt_list(conn, org) if d["card_id"]}
    for c in credit(conn, org, tz)["cards"]:
        if c["id"] not in linked and c["balance"]:
            owe.append({"name": c["name"], "value": c["balance"], "kind": "card"})
    return (sum(round(x["value"] * 100) for x in have), sum(round(x["value"] * 100) for x in owe), have, owe)


def net_worth(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """What you own (account balances you checked, and assets at the values you set) minus what you owe (debts and
    card balances). Snapshots show how it moves; save one a month."""
    a, d, have, owe = _totals(conn, org, tz)
    N = db.net_worth_snapshots
    snaps = conn.execute(select(N).where(N.c.organization_id == org).order_by(N.c.day.desc()).limit(24)).fetchall()
    return {"assets": a / 100, "debts": d / 100, "net": (a - d) / 100, "own": have, "owe": owe,
            "snapshots": [{"day": _day(s.day), "assets": s.assets_cents / 100, "debts": s.debts_cents / 100,
                           "net": (s.assets_cents - s.debts_cents) / 100} for s in reversed(snaps)]}


def snapshot(p: Principal, tz: str | None = "UTC") -> dict:
    d = _today(tz).isoformat()
    N = db.net_worth_snapshots
    with transaction() as conn:
        a, o, _, _ = _totals(conn, p.organization_id, tz)
        conn.execute(delete(N).where(N.c.organization_id == p.organization_id, N.c.day == d))
        conn.execute(insert(N).values(id=db.new_id(), organization_id=p.organization_id, day=d, assets_cents=a, debts_cents=o))
        _changed(conn, p.organization_id, "net_worth")
    return {"day": d, "net": (a - o) / 100}


# ---------------------------------------------------------------- V6.152 on-time streak

def streak(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Bills paid on time in a row, counting back from the most recent due date that has passed (or been paid), and
    your best run in the last two years. A late or missed bill resets the run."""
    from datetime import datetime
    from .taskplus import _zone
    zone = _zone(tz)
    today = _today(tz)
    P = db.my_bill_payments
    pays = {(r.bill_id, r.period): r.paid_at for r in conn.execute(select(P).where(P.c.organization_id == org))}
    events = []
    for b in bills(conn, org, tz, include_inactive=True):
        created = datetime.fromisoformat(str(b["created_at"]).replace("Z", "+00:00")).astimezone(zone).date()
        y, m = today.year - 2, today.month
        for _ in range(26):
            if b["cadence"] == "monthly":
                d = due_date(b, y, m)
            elif m == (b["due_month"] or 1):
                d = due_date(b, y)
            else:
                d = None
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            if d is None or d < created or d > today + timedelta(days=40):
                continue
            paid = pays.get((b["id"], period_of(b, d)))
            if paid:
                when = datetime.fromisoformat(str(paid).replace("Z", "+00:00")).astimezone(zone).date()
                events.append((d, when <= d))
            elif d < today and b["active"]:
                events.append((d, False))
    events.sort()
    run = best = 0
    for _, ok in events:
        run = run + 1 if ok else 0
        best = max(best, run)
    return {"current": run, "best": best, "counted": len(events)}


# ---------------------------------------------------------------- V6.151 monthly review

def review(conn: Connection, org: str, tz: str | None = "UTC", month: str | None = None) -> dict:
    """One month in numbers: income, spending against your limits, bills on time, savings and net worth change.
    Defaults to last month."""
    today = _today(tz)
    if not month:
        prev = today.replace(day=1) - timedelta(days=1)
        month = prev.strftime("%Y-%m")
    first, last = _month_bounds(month, today)
    I = db.income_entries
    inc = sum(r.amount_cents for r in conn.execute(select(I.c.amount_cents).where(
        I.c.organization_id == org, I.c.day >= first.isoformat(), I.c.day <= last.isoformat())))
    sp = spending(conn, org, tz, month)
    from .money import on_time
    rec = next((m for m in on_time(conn, org, tz, 24)["months"] if m["month"] == month), None)
    E = db.savings_entries
    saved = sum(r.amount_cents for r in conn.execute(select(E.c.amount_cents).where(
        E.c.organization_id == org, E.c.day >= first.isoformat(), E.c.day <= last.isoformat())))
    N = db.net_worth_snapshots
    snaps = conn.execute(select(N).where(N.c.organization_id == org, N.c.day <= last.isoformat()).order_by(N.c.day.desc())).fetchall()
    end = next((s for s in snaps if _day(s.day) >= first.isoformat()), None)
    start = next((s for s in snaps if _day(s.day) < first.isoformat()), None)
    nw = None
    if end and start:
        nw = ((end.assets_cents - end.debts_cents) - (start.assets_cents - start.debts_cents)) / 100
    over = [c["category"] for c in sp["categories"] if c["over"]]
    highlights = []
    if inc:
        highlights.append(f"You logged ${inc / 100:,.2f} of income.")
    if sp["total"]:
        highlights.append(f"You logged ${sp['total']:,.2f} of spending" + (f"; over the limit in {', '.join(over)}." if over else "."))
    if rec and (rec["on_time"] + rec["late"] + rec["missed"]):
        highlights.append(f"{rec['on_time']} bill{'s' if rec['on_time'] != 1 else ''} paid on time, {rec['late']} late, {rec['missed']} missed.")
    if saved:
        highlights.append(f"You put ${saved / 100:,.2f} toward savings goals." if saved > 0 else f"You took ${-saved / 100:,.2f} out of savings goals.")
    return {"month": month, "income": inc / 100, "spending": sp["total"], "categories": sp["categories"],
            "over_limit": over, "bills": rec, "saved": saved / 100, "kept": (inc - round(sp["total"] * 100)) / 100,
            "net_worth_change": nw, "highlights": highlights, "streak": streak(conn, org, tz)}


# ---------------------------------------------------------------- V6.153 split bills

def add_split(p: Principal, bid: str, person: str, share) -> dict:
    n = " ".join(str(person or "").split())[:40]
    if not n:
        raise PlusError("say who pays part")
    sid = db.new_id()
    with transaction() as conn:
        _row(conn, db.my_bills, p.organization_id, bid, "bill")
        S = db.bill_splits
        if len(conn.execute(select(S.c.id).where(S.c.bill_id == bid)).fetchall()) >= 8:
            raise PlusError("up to 8 people on a bill", 409)
        conn.execute(insert(S).values(id=sid, bill_id=bid, organization_id=p.organization_id, person=n, share_cents=_cents(share, "share")))
        _changed(conn, p.organization_id, "splits")
    return {"id": sid}


def remove_split(p: Principal, sid: str) -> None:
    with transaction() as conn:
        _row(conn, db.bill_splits, p.organization_id, sid, "split")
        conn.execute(delete(db.split_receipts).where(db.split_receipts.c.split_id == sid))
        conn.execute(delete(db.bill_splits).where(db.bill_splits.c.id == sid))
        _changed(conn, p.organization_id, "splits")


def mark_received(p: Principal, sid: str, period: str, received: bool = True) -> None:
    if not re.fullmatch(r"\d{4}(-(0[1-9]|1[0-2]))?", period or ""):
        raise PlusError("the period is YYYY-MM (or YYYY for a yearly bill)")
    R = db.split_receipts
    with transaction() as conn:
        _row(conn, db.bill_splits, p.organization_id, sid, "split")
        conn.execute(delete(R).where(R.c.split_id == sid, R.c.period == period))
        if received:
            conn.execute(insert(R).values(split_id=sid, period=period, organization_id=p.organization_id, received_at=_now().isoformat()))
        _changed(conn, p.organization_id, "splits")


def splits(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Who pays part of which bill, and whether they've paid you for this period. You collect it yourself."""
    S, R = db.bill_splits, db.split_receipts
    rows = conn.execute(select(S).where(S.c.organization_id == org)).fetchall()
    got = {(r.split_id, r.period): r.received_at for r in conn.execute(select(R).where(R.c.organization_id == org))}
    bmap = {b["id"]: b for b in bills(conn, org, tz, include_inactive=True)}
    out: dict[str, dict] = {}
    for r in rows:
        b = bmap.get(r.bill_id)
        if not b:
            continue
        e = out.setdefault(r.bill_id, {"bill_id": r.bill_id, "name": b["name"], "amount": b["amount"], "period": b["this_period"],
                                       "people": [], "your_share": None})
        e["people"].append({"id": r.id, "person": r.person, "share": r.share_cents / 100,
                            "received_at": got.get((r.id, b["this_period"]))})
    owed = 0
    for e in out.values():
        others = sum(round(x["share"] * 100) for x in e["people"])
        if e["amount"] is not None:
            e["your_share"] = max(0, round(e["amount"] * 100) - others) / 100
        owed += sum(round(x["share"] * 100) for x in e["people"] if not x["received_at"])
    return {"bills": sorted(out.values(), key=lambda x: x["name"].lower()), "owed_to_you": owed / 100}


# ---------------------------------------------------------------- V6.154 paycheck split

def paycheck_split(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Your next paycheck (or the current one), split: the bills due before the one after it, your savings plans for
    that stretch, and what's left to spend, per day. Needs a pay schedule with a usual amount."""
    plan = planner(conn, org, tz, 2)
    if not plan["has_schedule"]:
        return {"ready": False, "reason": "Add when you get paid, and what a paycheck usually is."}
    per = next((x for x in plan["periods"] if x["pay"] is not None), None)
    if per is None:
        return {"ready": False, "reason": "Add what a paycheck usually is to your pay schedule."}
    start, end = date.fromisoformat(per["from"]), date.fromisoformat(per["to"])
    days = max(1, (end - start).days)
    plan_m = sum(round((g["monthly_plan"] or 0) * 100) for g in goals(conn, org, tz) if not g["done"])
    save = round(plan_m * days / 30)
    pay = round(per["pay"] * 100)
    need = round(per["needed"] * 100)
    left = pay - need - save
    return {"ready": True, "from": per["from"], "to": per["to"], "payday": per["payday"], "pay": pay / 100,
            "bills": need / 100, "bills_vary": per["varies"], "savings": save / 100, "spending": left / 100,
            "per_day": round(max(0, left) / days / 100, 2), "days": days,
            "parts": [{"label": "Bills", "amount": need / 100}, {"label": "Savings", "amount": save / 100},
                      {"label": "Spending", "amount": max(0, left) / 100}],
            "short": left < 0, "note": ESTIMATE}
