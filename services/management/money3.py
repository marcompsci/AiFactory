"""Money, round 3 (V6.158–V6.187): paying on time, credit, earning and keeping more, and the assistant pieces (a
to-do feed, a weekly check-in, "can I afford it?").

Same rules as before: worked out from numbers you type in. Nothing is connected to a bank, nothing moves money, and
nothing here is financial, tax or credit advice. Estimates say they are estimates.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.auth import Principal
from services.core.events import transaction

from .money import (_canon, _cents, _changed, _date, _row, _today, bill_dates, credit, goals, income, on_time, paydays,
                    schedules, subscriptions)
from .money2 import NUMBERISH, _spent, accounts, bill_checks, safe_to_spend
from .taskextra import _day, _month_len, bills, due_date
from .taskplus import PlusError, _now

ESTIMATE = "An estimate from the numbers you entered, not advice."
BUREAUS = ("equifax", "experian", "transunion")
REPORTS_URL = "https://www.annualcreditreport.com"
FREEZE_URL = "https://www.identitytheft.gov/#/CreditBureauContacts"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
          "december"]


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _no_card_number(text: str, what: str) -> str:
    """Refuse text that holds what looks like a card number (13–19 digits that pass the card checksum) or a long run
    of digits such as an account number."""
    for m in re.finditer(r"(?:\d[ -]?){13,19}", text):
        d = re.sub(r"\D", "", m.group())
        if 13 <= len(d) <= 19 and _luhn(d):
            raise PlusError(f"that looks like a card number; leave it out of the {what}")
    if re.search(r"\d{17,}", re.sub(r"[ -]", "", text)):
        raise PlusError(f"leave account numbers out of the {what}")
    return text


def _text(v, n: int, what: str, required: bool = False) -> str:
    s = " ".join(str(v or "").split())[:n]
    if required and not s:
        raise PlusError(f"enter the {what}")
    return _no_card_number(s, what)


# ---------------------------------------------------------------- V6.158 paste a bill

_DATE_PATTERNS = (
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),                                           # 2026-12-15
    re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b"),                                 # 12/15(/2026)
    re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b"),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:,?\s+(\d{4}))?\b"),
)


def _dates(text: str, today: date) -> list[tuple[int, date]]:
    """Every date in the text with its position. A date with no year is the next one on or after today."""
    out = []
    low = text.lower()
    for i, rx in enumerate(_DATE_PATTERNS):
        for m in rx.finditer(low):
            try:
                if i == 0:
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                else:
                    if i == 1:
                        mo, dd, yy = int(m.group(1)), int(m.group(2)), m.group(3)
                    elif i == 2:
                        mo, dd, yy = MONTHS.index(next(x for x in MONTHS if x.startswith(m.group(1)[:3]))) + 1, int(m.group(2)), m.group(3)
                    else:
                        mo, dd, yy = MONTHS.index(next(x for x in MONTHS if x.startswith(m.group(2)[:3]))) + 1, int(m.group(1)), m.group(3)
                    if yy:
                        y = int(yy) + (2000 if len(yy) == 2 else 0)
                        d = date(y, mo, dd)
                    else:
                        d = date(today.year, mo, dd)
                        if d < today - timedelta(days=15):
                            d = date(today.year + 1, mo, dd)
            except (ValueError, StopIteration):
                continue
            out.append((m.start(), d))
    return sorted(out)


def parse_bill(text: str, tz: str | None = "UTC") -> dict:
    """Paste a bill email or text: find the biller, the amount due, the due date and whether it's on autopay.
    Nothing is saved; you check it and add the bill. Account numbers in the text are ignored."""
    raw = (text or "")[:5000]
    if not raw.strip():
        raise PlusError("paste the bill's email or text")
    today = _today(tz)
    low = raw.lower()
    amounts = [(m.start(), float(m.group(1).replace(",", ""))) for m in re.finditer(r"\$\s?(\d{1,6}(?:,\d{3})*(?:\.\d{2})?)", raw)]
    key_rx = re.compile(r"(amount due|total due|balance due|payment due|minimum payment|amount|total|balance|due)")
    keys = [m.start() for m in key_rx.finditer(low)]

    def near(pos: int) -> int:
        return min((abs(pos - k) for k in keys), default=10_000)

    amount = min(amounts, key=lambda a: (near(a[0]), a[0]))[1] if amounts else None
    due_keys = [m.start() for m in re.finditer(r"\bdue\b|\bpay by\b|\bpayment date\b|\bwill be (?:charged|debited|drafted)", low)]
    ds = _dates(raw, today)
    due = None
    if ds:
        due = min(ds, key=lambda d: (min((abs(d[0] - k) for k in due_keys), default=10_000), d[0]))[1]
    name = None
    m = re.search(r"\b[Yy]our ([A-Z][\w&'. ]{1,40}?) (?:bill|statement|payment|invoice)\b", raw)
    if m:
        name = m.group(1)
    if not name:
        m = re.search(r"\b[Ff]rom:?\s+([A-Z][\w&'. ]{1,40}?)(?:\s*<|\s*$|\n|,)", raw, re.M)
        if m:
            name = m.group(1)
    if not name:
        first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "Bill")
        name = re.sub(r"(?i)\b(re|fwd?|subject):\s*", "", first)[:40]
    name = re.sub(r"\d{6,}", "", name).strip(" -:,.") or "Bill"
    autopay = bool(re.search(r"auto ?pay|automatic payment|will be (?:automatically )?(?:charged|debited|drafted)|auto-?draft", low))
    yearly = bool(re.search(r"\b(annual|yearly|per year|12[- ]month)\b", low))
    return {"name": name[:60], "amount": amount, "due_date": due.isoformat() if due else None,
            "due_day": due.day if due else None, "due_month": due.month if due and yearly else None,
            "cadence": "yearly" if yearly else "monthly", "autopay": autopay,
            "found": {"amount": amount is not None, "due_date": due is not None},
            "note": "Check these before adding the bill. The pasted text isn't saved."}


# ---------------------------------------------------------------- V6.159 move a due date

def due_date_moves(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Monthly bills due in the 4 days before a payday (when money is usually tightest), with a due day a few days
    after payday to ask the biller for, and what to say. Many billers let you pick a due date; you ask, the app doesn't."""
    today = _today(tz)
    scheds = schedules(conn, org, tz)
    if not scheds:
        return {"ready": False, "reason": "Add when you get paid first.", "moves": []}
    days = sorted({d for s in scheds for d in paydays(s, today - timedelta(days=31), 8)})
    out = []
    for b in bills(conn, org, tz):
        if b["cadence"] != "monthly" or b["amount_cents"] is None:
            continue
        hits = 0
        for k in range(2):  # this month and next
            y, m = (today.year, today.month) if k == 0 else ((today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1))
            d = due_date(b, y, m)
            nxt = next((p for p in days if p >= d), None)
            if nxt and 0 < (nxt - d).days <= 4:
                hits += 1
                payday = nxt
        if hits:
            suggest = min(28, payday.day + 3)
            out.append({"bill_id": b["id"], "name": b["name"], "amount": b["amount"], "due_day": b["due_day"],
                        "payday": payday.isoformat(), "suggested_due_day": suggest,
                        "script": (f"Hi, I'd like to change the due date on my {b['name']} account. I get paid around the "
                                   f"{_ordinal(payday.day)}, so the {_ordinal(suggest)} would help me pay on time every month. "
                                   "Can you move it, and will it change this month's bill or add any fee?")})
    return {"ready": True, "moves": out,
            "note": "Ask before your next due date and keep paying on the current date until they confirm the change."}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ---------------------------------------------------------------- V6.161 confirmation numbers, V6.162 bill history

def set_payment_note(p: Principal, bid: str, period: str, confirmation: str | None, method: str | None) -> None:
    conf = _text(confirmation, 60, "confirmation number")
    meth = _text(method, 40, "payment method")
    N, P = db.payment_notes, db.my_bill_payments
    with transaction() as conn:
        _row(conn, db.my_bills, p.organization_id, bid, "bill")
        if not conn.execute(select(P.c.id).where(P.c.bill_id == bid, P.c.period == period)).first():
            raise PlusError("mark that period paid first", 409)
        conn.execute(delete(N).where(N.c.bill_id == bid, N.c.period == period))
        if conf or meth:
            conn.execute(insert(N).values(bill_id=bid, period=period, organization_id=p.organization_id, confirmation=conf, method=meth))
        _changed(conn, p.organization_id, "bills")


def bill_history(conn: Connection, org: str, bid: str, tz: str | None = "UTC") -> dict:
    """Up to 24 periods you marked paid: the amount, the day, on time or late, and the confirmation number."""
    from .taskplus import _zone
    b = next((x for x in bills(conn, org, tz, include_inactive=True) if x["id"] == bid), None) if _canon(bid) else None
    if b is None:
        raise PlusError("bill not found", 404)
    P, N = db.my_bill_payments, db.payment_notes
    notes = {r.period: r for r in conn.execute(select(N).where(N.c.bill_id == bid, N.c.organization_id == org))}
    zone = _zone(tz)
    rows = []
    for r in conn.execute(select(P).where(P.c.bill_id == bid, P.c.organization_id == org).order_by(P.c.period.desc()).limit(24)):
        y = int(r.period[:4])
        d = due_date(b, y, int(r.period[5:7])) if "-" in r.period else due_date(b, y)
        paid = datetime.fromisoformat(str(r.paid_at).replace("Z", "+00:00")).astimezone(zone).date()
        n = notes.get(r.period)
        rows.append({"period": r.period, "due": d.isoformat(), "paid_on": paid.isoformat(), "on_time": paid <= d,
                     "amount": r.amount_cents / 100 if r.amount_cents is not None else None,
                     "confirmation": n.confirmation if n else "", "method": n.method if n else ""})
    amts = [x["amount"] for x in rows if x["amount"] is not None]
    return {"bill_id": bid, "name": b["name"], "payments": rows,
            "average": round(sum(amts) / len(amts), 2) if amts else None,
            "highest": max(amts) if amts else None, "lowest": min(amts) if amts else None}


# ---------------------------------------------------------------- V6.163 30-day forecast, V6.164 low points

def _avg_daily_spend(conn: Connection, org: str, today: date) -> int:
    rows = _spent(conn, org, today - timedelta(days=59), today)
    return round(sum(r.amount_cents for r in rows) / 60) if rows else 0


def forecast(conn: Connection, org: str, tz: str | None = "UTC", days: int = 30, buffer: float = 100) -> dict:
    """Day by day for the next `days` days: your checking and cash balance as you last entered it, plus paydays (when
    you've said what a paycheck usually is), minus unpaid bills on their due dates, minus your average daily spending
    over the last 60 days. Shows the lowest day and any days under `buffer` or below zero. An estimate."""
    today = _today(tz)
    have = [a for a in accounts(conn, org) if a["kind"] in ("checking", "cash") and a["balance"] is not None]
    if not have:
        return {"ready": False, "reason": "Add a checking account and its balance to see this.", "note": ESTIMATE}
    newest = max(date.fromisoformat(a["as_of"]) for a in have)
    bal = sum(round(a["balance"] * 100) for a in have)
    bal -= sum(r.amount_cents for r in _spent(conn, org, newest + timedelta(days=1), today))
    end = today + timedelta(days=days)
    events: dict[date, list] = {}
    for b in bills(conn, org, tz):
        for d in bill_dates(b, today, end + timedelta(days=1), include_overdue=True):
            when = max(d, today)
            events.setdefault(when, []).append({"kind": "bill", "name": b["name"], "amount": -(b["amount_cents"] or 0) / 100,
                                                "varies": b["amount_cents"] is None})
    for s in schedules(conn, org, tz):
        if s["amount_cents"] is None:
            continue
        for d in paydays(s, today + timedelta(days=1), 40):
            if d > end:
                break
            events.setdefault(d, []).append({"kind": "pay", "name": s["name"], "amount": s["amount_cents"] / 100, "varies": False})
    spend = _avg_daily_spend(conn, org, today)
    out = []
    cur = bal
    for k in range(days + 1):
        d = today + timedelta(days=k)
        ev = events.get(d, [])
        cur += sum(round(e["amount"] * 100) for e in ev)
        if k:
            cur -= spend
        out.append({"day": d.isoformat(), "balance": cur / 100, "events": ev})
    low = min(out, key=lambda x: x["balance"])
    buf = round(buffer * 100)
    return {"ready": True, "start": bal / 100, "daily_spending": spend / 100, "days": out, "low": low,
            "below_zero": [x["day"] for x in out if x["balance"] < 0],
            "below_buffer": [x["day"] for x in out if 0 <= x["balance"] * 100 < buf], "buffer": buffer,
            "bills_that_vary": sum(1 for x in out for e in x["events"] if e["varies"]),
            "note": "Bills that vary aren't counted. " + ESTIMATE}


# ---------------------------------------------------------------- V6.165 credit reports, V6.167 freezes, V6.166 disputes

def _checks(conn: Connection, org: str, prefix: str) -> dict[str, str]:
    M = db.money_checks
    return {r.key.split(":", 1)[1]: r.done_at for r in conn.execute(select(M).where(M.c.organization_id == org))
            if r.key.startswith(prefix + ":")}


def credit_watch(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """When you last checked each bureau's free report, whether each file is frozen, and your disputes."""
    today = _today(tz)
    checked = _checks(conn, org, "report")
    frozen = _checks(conn, org, "freeze")
    rows = []
    for b in BUREAUS:
        at = checked.get(b)
        age = (today - datetime.fromisoformat(str(at).replace("Z", "+00:00")).date()).days if at else None
        rows.append({"bureau": b, "checked_at": at, "days_since": age, "due": age is None or age > 30,
                     "frozen": b in frozen, "frozen_at": frozen.get(b)})
    D = db.credit_disputes
    disputes = []
    for r in conn.execute(select(D).where(D.c.organization_id == org).order_by(D.c.sent_on.desc())):
        sent = date.fromisoformat(_day(r.sent_on))
        follow = sent + timedelta(days=35)
        disputes.append({"id": r.id, "bureau": r.bureau, "item": r.item, "sent_on": sent.isoformat(), "status": r.status,
                         "note": r.note, "closed_on": _day(r.closed_on) if r.closed_on else None,
                         "follow_up_on": follow.isoformat(), "follow_up_due": r.status == "open" and today >= follow})
    return {"bureaus": rows, "disputes": disputes, "reports_url": REPORTS_URL, "freeze_url": FREEZE_URL,
            "note": ("You can get a free report from each bureau every week at AnnualCreditReport.com. Freezing and "
                     "unfreezing is free. When you dispute an error, the bureau generally has about 30 days to "
                     "investigate. General information, not advice.")}


def mark_bureau(p: Principal, kind: str, bureau: str, on: bool = True) -> None:
    if kind not in ("report", "freeze") or bureau not in BUREAUS:
        raise PlusError("not a bureau check", 404)
    M = db.money_checks
    key = f"{kind}:{bureau}"
    with transaction() as conn:
        conn.execute(delete(M).where(M.c.organization_id == p.organization_id, M.c.key == key))
        if on:
            conn.execute(insert(M).values(organization_id=p.organization_id, key=key, done_at=_now().isoformat()))
        _changed(conn, p.organization_id, "credit")


def add_dispute(p: Principal, bureau: str, item: str, sent_on: str | None = None, note: str | None = None,
                tz: str | None = "UTC") -> dict:
    if bureau not in (*BUREAUS, "other"):
        raise PlusError("pick Equifax, Experian, TransUnion or other")
    d = _date(sent_on, "day you sent it") if sent_on else _today(tz)
    if d > _today(tz):
        raise PlusError("the day can't be in the future")
    did = db.new_id()
    with transaction() as conn:
        conn.execute(insert(db.credit_disputes).values(id=did, organization_id=p.organization_id, bureau=bureau,
                                                       item=_text(item, 120, "item", required=True), sent_on=d.isoformat(),
                                                       status="open", note=_text(note, 300, "note")))
        _changed(conn, p.organization_id, "credit")
    return {"id": did}


def update_dispute(p: Principal, did: str, status: str, note: str | None = None, tz: str | None = "UTC") -> None:
    if status not in ("open", "fixed", "denied"):
        raise PlusError("a dispute is open, fixed or denied")
    D = db.credit_disputes
    with transaction() as conn:
        _row(conn, D, p.organization_id, did, "dispute")
        vals = {"status": status, "closed_on": None if status == "open" else _today(tz).isoformat()}
        if note is not None:
            vals["note"] = _text(note, 300, "note")
        conn.execute(update(D).where(D.c.id == did).values(**vals))
        _changed(conn, p.organization_id, "credit")


def remove_dispute(p: Principal, did: str) -> None:
    with transaction() as conn:
        _row(conn, db.credit_disputes, p.organization_id, did, "dispute")
        conn.execute(delete(db.credit_disputes).where(db.credit_disputes.c.id == did))
        _changed(conn, p.organization_id, "credit")


# ---------------------------------------------------------------- V6.168 credit habits, V6.169 utilization history

def habits(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Habits lenders and the bureaus commonly describe, each checked against your own numbers. General information;
    it isn't a score and can't say what any lender will do."""
    c = credit(conn, org, tz)
    rec = c["record"]
    w = credit_watch(conn, org, tz)
    items = []

    def add(key: str, title: str, state: str, detail: str) -> None:
        items.append({"key": key, "title": title, "state": state, "detail": detail})

    if rec["on_time_rate"] is None:
        add("on_time", "Pay every bill on time", "unknown", "Mark bills paid when you pay them to track this.")
    else:
        late = rec["late"] + rec["missed"]
        add("on_time", "Pay every bill on time", "good" if not late else "attention",
            f"{round(rec['on_time_rate'] * 100)}% on time over the last 12 months" + (f"; {late} late or missed." if late else "."))
    if c["utilization"] is None:
        add("utilization", "Keep card balances low", "unknown", "Add your cards under Credit to track this.")
    else:
        over = [x["name"] for x in c["cards"] if x["utilization"] > 0.3]
        add("utilization", "Keep card balances low", "good" if c["utilization"] <= 0.3 and not over else "attention",
            f"{round(c['utilization'] * 100)}% used overall" + (f"; over 30% on {', '.join(over)}." if over else "."))
    due = [b["bureau"].title() for b in w["bureaus"] if b["due"]]
    add("reports", "Check your credit reports for errors", "good" if not due else "attention",
        "Checked all three in the last month." if not due else f"Not checked in the last month: {', '.join(due)}.")
    open_d = [d for d in w["disputes"] if d["status"] == "open"]
    if open_d:
        add("disputes", "Follow up on disputes", "attention" if any(d["follow_up_due"] for d in open_d) else "good",
            f"{len(open_d)} open" + ("; one is past about 30 days, so follow up." if any(d["follow_up_due"] for d in open_d) else "."))
    add("accounts", "Keep older accounts open when you can", "info",
        "The age of your accounts is part of most credit scores; closing an old card can shorten it and raise utilization.")
    add("applications", "Apply for new credit only when you need it", "info",
        "Each application can add a hard inquiry, which may lower a score a little for a while.")
    return {"items": items, "note": "General information about common credit habits, not advice and not a score."}


def record_card(conn: Connection, org: str, cid: str, balance_cents: int, limit_cents: int, day: date) -> None:
    """Called when a card's balance or limit changes: one history point a day (V6.169)."""
    H = db.card_history
    conn.execute(delete(H).where(H.c.card_id == cid, H.c.day == day.isoformat()))
    conn.execute(insert(H).values(id=db.new_id(), card_id=cid, organization_id=org, balance_cents=balance_cents,
                                  limit_cents=limit_cents, day=day.isoformat()))


def utilization_history(conn: Connection, org: str, tz: str | None = "UTC", months: int = 12) -> dict:
    """Overall utilization over time: on each day you updated any card, every card's latest balance and limit as of
    that day (cards count from the day you first entered them)."""
    today = _today(tz)
    H = db.card_history
    rows = conn.execute(select(H).where(H.c.organization_id == org, H.c.day >= (today - timedelta(days=31 * months)).isoformat())
                        .order_by(H.c.day)).fetchall()
    cards = {c["id"] for c in credit(conn, org, tz)["cards"]}
    latest: dict[str, tuple[int, int]] = {}
    points = []
    for day in sorted({_day(r.day) for r in rows}):
        for r in rows:
            if _day(r.day) == day and r.card_id in cards:
                latest[r.card_id] = (r.balance_cents, r.limit_cents)
        bal = sum(v[0] for v in latest.values())
        lim = sum(v[1] for v in latest.values())
        if lim:
            points.append({"day": day, "utilization": round(bal / lim, 3), "balance": bal / 100, "limit": lim / 100})
    return {"points": points}


# ---------------------------------------------------------------- V6.170 a card's payment as a bill

def card_bill(p: Principal, cid: str, due_day: int, tz: str | None = "UTC") -> dict:
    """Make (or move) a monthly bill for a card's payment, due on the day you give. Its amount varies; set reminders
    and mark it paid like any bill."""
    from . import taskextra
    if not isinstance(due_day, int) or not 1 <= due_day <= 31:
        raise PlusError("the due day is 1 to 31")
    CB = db.card_bills
    with db.get_engine().connect() as conn:
        card = _row(conn, db.credit_cards, p.organization_id, cid, "card")
        link = conn.execute(select(CB).where(CB.c.card_id == cid)).first()
        live = link and conn.execute(select(db.my_bills.c.id).where(db.my_bills.c.id == link.bill_id)).first()
    if live:
        return taskextra.edit_bill(p, link.bill_id, {"due_day": due_day}, tz)
    b = taskextra.add_bill(p, {"name": f"{card.name} payment", "amount": None, "due_day": due_day, "cadence": "monthly",
                               "notes": "Card payment: at least the minimum. Paying the statement balance avoids interest on most cards."},
                           tz)
    with transaction() as conn:
        conn.execute(delete(CB).where(CB.c.card_id == cid))
        conn.execute(insert(CB).values(card_id=cid, organization_id=p.organization_id, bill_id=b["id"]))
        _changed(conn, p.organization_id, "credit")
    return b


def card_bill_links(conn: Connection, org: str) -> dict[str, str]:
    CB = db.card_bills
    return {r.card_id: r.bill_id for r in conn.execute(select(CB).where(CB.c.organization_id == org))}


# ---------------------------------------------------------------- V6.171 income goal, V6.172 best days

def set_income_goal(p: Principal, monthly) -> None:
    T = db.money_targets
    v = None if monthly in (None, "", 0) else _cents(monthly, "goal")
    with transaction() as conn:
        conn.execute(delete(T).where(T.c.organization_id == p.organization_id))
        conn.execute(insert(T).values(organization_id=p.organization_id, monthly_income_cents=v))
        _changed(conn, p.organization_id, "income")


def income_goal(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """This month's income against your goal: what's left, per day for the days left, and (from your logged hourly
    rate) about how many hours that is."""
    T = db.money_targets
    r = conn.execute(select(T).where(T.c.organization_id == org)).first()
    goal = r.monthly_income_cents if r else None
    today = _today(tz)
    inc = income(conn, org, tz, 90)
    have = round(inc["month_total"] * 100)
    days_left = _month_len(today.year, today.month) - today.day + 1
    rate = inc["month_hourly"] or _rate_90(inc)
    if not goal:
        return {"goal": None, "earned": have / 100, "days_left": days_left}
    left = max(0, goal - have)
    return {"goal": goal / 100, "earned": have / 100, "left": left / 100, "progress": round(min(have / goal, 1.5), 3),
            "days_left": days_left, "per_day": round(left / days_left / 100, 2), "hourly": rate,
            "hours_needed": round(left / 100 / rate, 1) if rate and left else (0 if not left else None), "reached": left == 0}


def _rate_90(inc: dict) -> float | None:
    timed = [e for e in inc["entries"] if e["hours"]]
    hrs = sum(e["hours"] for e in timed)
    return round(sum(e["amount"] for e in timed) / hrs, 2) if hrs else None


def best_days(conn: Connection, org: str, tz: str | None = "UTC", days: int = 90, source: str | None = None) -> dict:
    """By weekday over the last `days` days: what you earned, your hours, and per hour (from entries with hours).
    Optionally for one income source. Useful for choosing when to drive or pick up shifts; past results only."""
    today = _today(tz)
    I = db.income_entries
    q = select(I).where(I.c.organization_id == org, I.c.day >= (today - timedelta(days=days)).isoformat())
    rows = [r for r in conn.execute(q) if not source or r.source.lower() == source.lower()]
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    by = {i: {"earned": 0, "hours": 0.0, "timed": 0, "entries": 0} for i in range(7)}
    for r in rows:
        w = date.fromisoformat(_day(r.day)).weekday()
        by[w]["earned"] += r.amount_cents
        by[w]["entries"] += 1
        if r.hours:
            by[w]["hours"] += r.hours
            by[w]["timed"] += r.amount_cents
    out = [{"weekday": names[i], "earned": v["earned"] / 100, "hours": round(v["hours"], 1), "entries": v["entries"],
            "hourly": round(v["timed"] / v["hours"] / 100, 2) if v["hours"] else None} for i, v in by.items()]
    ranked = sorted((x for x in out if x["hourly"] is not None), key=lambda x: -x["hourly"])
    return {"days": out, "best": [x["weekday"] for x in ranked[:2]], "sources": sorted({r.source for r in rows}),
            "note": "From what you logged in the last 90 days. Past earnings don't guarantee future ones."}


# ---------------------------------------------------------------- V6.173 wins, V6.174 selling, V6.175 owed to you

def add_win(p: Principal, title: str, amount, monthly: bool = False, day: str | None = None, tz: str | None = "UTC") -> dict:
    d = _date(day) if day else _today(tz)
    if d > _today(tz):
        raise PlusError("the day can't be in the future")
    wid = db.new_id()
    with transaction() as conn:
        conn.execute(insert(db.money_wins).values(id=wid, organization_id=p.organization_id, title=_text(title, 80, "what you saved", True),
                                                  amount_cents=_cents(amount), monthly=int(bool(monthly)), day=d.isoformat()))
        _changed(conn, p.organization_id, "wins")
    return {"id": wid}


def remove_win(p: Principal, wid: str) -> None:
    with transaction() as conn:
        _row(conn, db.money_wins, p.organization_id, wid, "win")
        conn.execute(delete(db.money_wins).where(db.money_wins.c.id == wid))
        _changed(conn, p.organization_id, "wins")


def wins(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Money you saved: one-time wins (a refund, a waived fee) and monthly ones (a lower bill). Totals for this year,
    counting a monthly win for each month since it started."""
    today = _today(tz)
    W = db.money_wins
    rows = conn.execute(select(W).where(W.c.organization_id == org).order_by(W.c.day.desc())).fetchall()
    y0 = date(today.year, 1, 1)
    year = 0
    for r in rows:
        d = date.fromisoformat(_day(r.day))
        if r.monthly:
            start = max(d, y0)
            months = (today.year - start.year) * 12 + today.month - start.month + 1 if start <= today else 0
            year += r.amount_cents * months
        elif d >= y0:
            year += r.amount_cents
    return {"wins": [{"id": r.id, "title": r.title, "amount": r.amount_cents / 100, "monthly": bool(r.monthly), "day": _day(r.day)} for r in rows],
            "this_year": year / 100, "per_month_ongoing": sum(r.amount_cents for r in rows if r.monthly) / 100}


def save_item(p: Principal, iid: str | None, fields: dict, tz: str | None = "UTC") -> dict:
    S = db.sell_items
    vals: dict = {}
    if "name" in fields or iid is None:
        vals["name"] = _text(fields.get("name"), 80, "item", True)
    if "asking" in fields:
        vals["asking_cents"] = None if fields["asking"] in (None, "") else _cents(fields["asking"], "asking price", allow_zero=True)
    if "where_listed" in fields:
        vals["where_listed"] = _text(fields["where_listed"], 60, "where it's listed")
    if "sold" in fields:
        if fields["sold"] in (None, ""):
            vals["sold_cents"], vals["sold_on"] = None, None
        else:
            vals["sold_cents"] = _cents(fields["sold"], "sold price", allow_zero=True)
            vals["sold_on"] = _today(tz).isoformat()
    with transaction() as conn:
        if iid is None:
            if len(conn.execute(select(S.c.id).where(S.c.organization_id == p.organization_id)).fetchall()) >= 200:
                raise PlusError("up to 200 items", 409)
            iid = db.new_id()
            conn.execute(insert(S).values(id=iid, organization_id=p.organization_id, listed_on=_today(tz).isoformat(),
                                          where_listed=vals.pop("where_listed", ""), **vals))
        else:
            _row(conn, S, p.organization_id, iid, "item")
            if vals:
                conn.execute(update(S).where(S.c.id == iid).values(**vals))
        _changed(conn, p.organization_id, "selling")
    return {"id": iid}


def remove_item(p: Principal, iid: str) -> None:
    with transaction() as conn:
        _row(conn, db.sell_items, p.organization_id, iid, "item")
        conn.execute(delete(db.sell_items).where(db.sell_items.c.id == iid))
        _changed(conn, p.organization_id, "selling")


def selling(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    today = _today(tz)
    S = db.sell_items
    rows = conn.execute(select(S).where(S.c.organization_id == org).order_by(S.c.sold_on.is_(None).desc(), S.c.listed_on.desc())).fetchall()
    y0 = date(today.year, 1, 1).isoformat()
    items = [{"id": r.id, "name": r.name, "asking": r.asking_cents / 100 if r.asking_cents is not None else None,
              "sold": r.sold_cents / 100 if r.sold_cents is not None else None, "where_listed": r.where_listed,
              "listed_on": _day(r.listed_on), "sold_on": _day(r.sold_on) if r.sold_on else None,
              "days_listed": (today - date.fromisoformat(_day(r.listed_on))).days} for r in rows]
    return {"items": items, "listed": sum(1 for x in items if x["sold"] is None),
            "listed_value": round(sum(x["asking"] or 0 for x in items if x["sold"] is None), 2),
            "sold_this_year": round(sum(x["sold"] for x in items if x["sold"] is not None and (x["sold_on"] or "") >= y0), 2)}


def add_owed(p: Principal, who: str, amount, why: str | None = None, expected_on: str | None = None) -> dict:
    exp = _date(expected_on, "day you expect it") if expected_on else None
    oid = db.new_id()
    with transaction() as conn:
        conn.execute(insert(db.owed_to_me).values(id=oid, organization_id=p.organization_id, who=_text(who, 40, "who", True),
                                                  amount_cents=_cents(amount), why=_text(why, 120, "reason"),
                                                  expected_on=exp.isoformat() if exp else None, created_at=_now().isoformat()))
        _changed(conn, p.organization_id, "owed")
    return {"id": oid}


def mark_owed(p: Principal, oid: str, received: bool, tz: str | None = "UTC") -> None:
    O = db.owed_to_me
    with transaction() as conn:
        _row(conn, O, p.organization_id, oid, "entry")
        conn.execute(update(O).where(O.c.id == oid).values(received_on=_today(tz).isoformat() if received else None))
        _changed(conn, p.organization_id, "owed")


def remove_owed(p: Principal, oid: str) -> None:
    with transaction() as conn:
        _row(conn, db.owed_to_me, p.organization_id, oid, "entry")
        conn.execute(delete(db.owed_to_me).where(db.owed_to_me.c.id == oid))
        _changed(conn, p.organization_id, "owed")


def owed(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Money people or companies owe you. You collect it; the app doesn't contact anyone."""
    today = _today(tz)
    O = db.owed_to_me
    rows = conn.execute(select(O).where(O.c.organization_id == org).order_by(O.c.received_on.is_(None).desc(), O.c.created_at.desc())).fetchall()
    items = [{"id": r.id, "who": r.who, "amount": r.amount_cents / 100, "why": r.why,
              "expected_on": _day(r.expected_on) if r.expected_on else None, "received_on": _day(r.received_on) if r.received_on else None,
              "late": bool(r.expected_on and not r.received_on and date.fromisoformat(_day(r.expected_on)) < today)} for r in rows]
    open_ = [x for x in items if not x["received_on"]]
    return {"items": items, "outstanding": round(sum(x["amount"] for x in open_), 2), "late": sum(1 for x in open_ if x["late"])}


# ---------------------------------------------------------------- V6.176 round-ups, V6.177 no-spend days

def round_ups(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """If every purchase you logged this month were rounded up to the next dollar, the change would come to this. A
    suggestion to move into savings yourself; nothing is moved."""
    today = _today(tz)
    rows = _spent(conn, org, today.replace(day=1), today)
    change = sum((100 - r.amount_cents % 100) % 100 for r in rows)
    return {"month": today.strftime("%Y-%m"), "purchases": len(rows), "round_ups": change / 100,
            "note": "Move it to a savings goal yourself, then record the deposit there."}


def toggle_no_spend(p: Principal, day: str | None, on: bool, tz: str | None = "UTC") -> None:
    d = _date(day) if day else _today(tz)
    if d > _today(tz) or d < _today(tz) - timedelta(days=60):
        raise PlusError("pick today or a day in the last 60")
    N = db.no_spend_days
    with transaction() as conn:
        conn.execute(delete(N).where(N.c.organization_id == p.organization_id, N.c.day == d.isoformat()))
        if on:
            conn.execute(insert(N).values(organization_id=p.organization_id, day=d.isoformat()))
        _changed(conn, p.organization_id, "no_spend")


def no_spend(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Days you marked no-spend: this month's count and your current run (today counts once marked; until then the
    run counts back from yesterday). A marked day with spending logged is flagged."""
    today = _today(tz)
    N = db.no_spend_days
    marked = {date.fromisoformat(_day(r.day)) for r in conn.execute(select(N).where(N.c.organization_id == org))}
    spent_days = {date.fromisoformat(_day(r.day)) for r in _spent(conn, org, today - timedelta(days=60), today)}
    d = today if today in marked else today - timedelta(days=1)
    run = 0
    while d in marked and d not in spent_days:
        run += 1
        d -= timedelta(days=1)
    first = today.replace(day=1)
    return {"this_month": sum(1 for x in marked if x >= first), "streak": run, "today": today in marked,
            "days": sorted(x.isoformat() for x in marked if x >= today - timedelta(days=60)),
            "conflicts": sorted(x.isoformat() for x in marked & spent_days)}


# ---------------------------------------------------------------- V6.178 set-asides for yearly bills

def sinking_funds(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """Each yearly bill with an amount: how much to set aside a month to have it by its due date."""
    today = _today(tz)
    out = []
    for b in bills(conn, org, tz):
        if b["cadence"] != "yearly" or b["amount_cents"] is None:
            continue
        due = date.fromisoformat(b["next_due"])
        months = max(1, (due.year - today.year) * 12 + due.month - today.month)
        out.append({"bill_id": b["id"], "name": b["name"], "amount": b["amount"], "due": due.isoformat(), "months": months,
                    "per_month": round(b["amount_cents"] / months / 100, 2)})
    out.sort(key=lambda x: x["due"])
    return {"funds": out, "per_month_total": round(sum(x["per_month"] for x in out), 2)}


def fund_goal(p: Principal, bid: str, tz: str | None = "UTC") -> dict:
    """Make a savings goal for a yearly bill: its amount by the day before it's due, with the monthly plan."""
    from .money import add_goal
    with db.get_engine().connect() as conn:
        f = next((x for x in sinking_funds(conn, p.organization_id, tz)["funds"] if x["bill_id"] == bid), None) if _canon(bid) else None
    if f is None:
        raise PlusError("that isn't a yearly bill with an amount", 404)
    deadline = date.fromisoformat(f["due"]) - timedelta(days=1)
    if deadline <= _today(tz):
        raise PlusError("that bill is due too soon for a goal")
    return add_goal(p, f"Set aside: {f['name']}"[:60], f["amount"], deadline.isoformat(), f["per_month"], tz)


# ---------------------------------------------------------------- V6.181 can I afford it?

def afford(conn: Connection, org: str, amount: float, tz: str | None = "UTC") -> dict:
    """Whether a purchase fits what's safe to spend before payday and what it does to your lowest forecast day.
    An estimate from your numbers; whether to buy it is your call."""
    if not 0 < amount <= 1_000_000:
        raise PlusError("the amount is more than 0")
    s = safe_to_spend(conn, org, tz)
    if not s["ready"]:
        return {"ready": False, "reason": s["reason"]}
    c = round(amount * 100)
    left = round(s["left"] * 100)
    after = left - c
    per_after = round(max(0, after) / s["days"] / 100, 2)
    f = forecast(conn, org, tz)
    low_after = round(f["low"]["balance"] - amount, 2) if f.get("ready") else None
    if after < 0:
        verdict, why = "short", f"It's ${-after / 100:,.2f} more than what's left before payday after bills and savings plans."
    elif s["per_day"] and per_after < s["per_day"] * 0.5:
        verdict, why = "tight", f"It fits, but leaves about ${per_after:,.2f} a day until payday (from ${s['per_day']:,.2f})."
    else:
        verdict, why = "fits", f"It fits, leaving about ${per_after:,.2f} a day until payday."
    if low_after is not None and low_after < 0 and verdict == "fits":
        verdict, why = "tight", why + f" Your lowest forecast day would drop to ${low_after:,.2f}."
    return {"ready": True, "amount": amount, "verdict": verdict, "why": why, "left_before": s["left"], "left_after": after / 100,
            "per_day_before": s["per_day"], "per_day_after": per_after, "days": s["days"], "low_after": low_after, "note": ESTIMATE}


# ---------------------------------------------------------------- V6.182 goal projections

def projections(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """For each open savings goal: the pace (what you put in over the last 90 days, or your monthly plan if that's
    all there is) and the month it'd be reached at that pace, against the deadline."""
    today = _today(tz)
    E = db.savings_entries
    out = []
    for g in goals(conn, org, tz):
        if g["done"]:
            continue
        recent = sum(r.amount_cents for r in conn.execute(select(E.c.amount_cents).where(
            E.c.goal_id == g["id"], E.c.organization_id == org, E.c.day >= (today - timedelta(days=90)).isoformat())))
        pace = round(recent / 3) if recent > 0 else round((g["monthly_plan"] or 0) * 100)
        left = round(g["left"] * 100)
        months = -(-left // pace) if pace > 0 else None
        reach = None
        if months is not None:
            y, m = today.year, today.month + months
            y += (m - 1) // 12
            m = (m - 1) % 12 + 1
            reach = f"{y:04d}-{m:02d}"
        on_track = None
        if g["deadline"] and reach:
            on_track = reach <= g["deadline"][:7]
        out.append({"goal_id": g["id"], "name": g["name"], "left": g["left"], "pace_per_month": pace / 100,
                    "pace_from": "deposits" if recent > 0 else ("plan" if pace else None), "months": months, "reach": reach,
                    "deadline": g["deadline"], "on_track": on_track})
    return {"goals": out, "note": ESTIMATE}


# ---------------------------------------------------------------- V6.180 money to-dos, V6.179 weekly check-in

def todos(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """What's worth doing next, most urgent first, from everything you've entered. Each item says where to go."""
    today = _today(tz)
    items = []

    def add(rank: int, key: str, title: str, detail: str, where: str) -> None:
        items.append({"rank": rank, "key": key, "title": title, "detail": detail, "where": where})

    bs = bills(conn, org, tz)
    for b in bs:
        if b["overdue"]:
            add(0, f"overdue:{b['id']}", f"{b['name']} is past due", f"Due {b['next_due']}. Pay it, or mark it paid if you already did.", "bills")
    s = safe_to_spend(conn, org, tz)
    if s["ready"] and s.get("short"):
        add(0, "short", "Bills before payday are more than you have", s.get("warning") or "Look at Safe to spend.", "safe")
    ch = bill_checks(conn, org, tz)
    for c in ch["autopay"]:
        if c["covered"] is False:
            add(1, f"autopay:{c['account_id']}", f"Autopay may not be covered in {c['account']}", f"Short about ${c['short_by']:,.2f} before payday.", "checks")
    f = forecast(conn, org, tz)
    if f.get("ready") and f["below_zero"]:
        add(1, "forecast", "Your balance may go below zero", f"First on {f['below_zero'][0]} in the 30-day forecast.", "forecast")
    accts = [a for a in accounts(conn, org) if a["kind"] in ("checking", "cash")]
    if not accts or all(a["balance"] is None for a in accts):
        add(3, "balance:none", "Add your checking balance", "Safe to spend and the forecast need it.", "accounts")
    else:
        stale = [a for a in accts if a["as_of"] and (today - date.fromisoformat(a["as_of"])).days >= 3]
        if stale:
            add(2, "balance:stale", "Update your balance", f"{', '.join(a['name'] for a in stale)} last updated {stale[0]['as_of']}.", "accounts")
    for card in credit(conn, org, tz)["cards"]:
        ns = card.get("next_statement")
        if card["utilization"] > 0.3 and ns and (date.fromisoformat(ns) - today).days <= 7:
            add(2, f"card:{card['id']}", f"{card['name']} is over 30% used", f"Its statement closes {ns}; paying some before then lowers what's reported.", "paydown")
    w = credit_watch(conn, org, tz)
    for d in w["disputes"]:
        if d["follow_up_due"]:
            add(2, f"dispute:{d['id']}", f"Follow up on your {d['bureau'].title()} dispute", f"Sent {d['sent_on']}: {d['item']}.", "credit")
    if all(b["due"] for b in w["bureaus"]):
        add(4, "reports", "Check your free credit reports", "Free every week at AnnualCreditReport.com.", "credit")
    for o in owed(conn, org, tz)["items"]:
        if o["late"]:
            add(3, f"owed:{o['id']}", f"{o['who']} owes you ${o['amount']:,.2f}", f"Expected {o['expected_on']}.", "owed")
    for sub in subscriptions(conn, org, tz)["subscriptions"]:
        if sub["review_due"]:
            add(4, f"sub:{sub['bill_id']}", f"Is {sub['name']} still worth it?", f"${sub['yearly']:,.2f} a year.", "subs")
    for c in ch["amount_changes"]:
        if c["change"] >= 0.1:
            add(3, f"jump:{c['bill_id']}", f"{c['name']} went up", f"${c['before']:,.2f} → ${c['last']:,.2f}. A call might lower it.", "checks")
    for m in due_date_moves(conn, org, tz)["moves"][:2]:
        add(4, f"move:{m['bill_id']}", f"Ask to move {m['name']}'s due date", f"It's due just before payday; the {_ordinal(m['suggested_due_day'])} would be easier.", "moves")
    if not schedules(conn, org, tz):
        add(3, "setup:pay", "Add when you get paid", "Most of the planning works from your paydays.", "plan")
    if not bs:
        add(3, "setup:bills", "Add your bills", "Paste a bill email or add them by hand.", "bills")
    items.sort(key=lambda x: (x["rank"], x["title"]))
    return {"items": items[:20], "count": len(items)}


def weekly(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    """The week ahead: bills in the next 7 days, safe to spend, your income goal, money owed to you, and the top to-dos."""
    today = _today(tz)
    soon = [b for b in bills(conn, org, tz) if b["overdue"] or 0 <= b["days_until"] <= 7]
    s = safe_to_spend(conn, org, tz)
    return {"week_of": today.isoformat(),
            "bills": [{"id": b["id"], "name": b["name"], "due": b["next_due"], "amount": b["amount"], "overdue": b["overdue"],
                       "autopay": b["autopay"]} for b in soon],
            "bills_total": round(sum(b["amount"] or 0 for b in soon), 2),
            "safe_per_day": s.get("per_day") if s["ready"] else None, "income_goal": income_goal(conn, org, tz),
            "owed_to_you": owed(conn, org, tz)["outstanding"], "todos": todos(conn, org, tz)["items"][:5]}


# ---------------------------------------------------------------- V6.183 export, V6.185 setup

EXPORT_TABLES = ("income_entries", "pay_schedules", "savings_goals", "savings_entries", "my_bills", "my_bill_payments",
                 "payment_notes", "bill_meta", "bill_extras", "bill_splits", "split_receipts", "credit_cards", "card_history",
                 "debts", "expenses", "category_budgets", "cash_accounts", "cash_balances", "gig_costs", "cashback_entries",
                 "assets", "net_worth_snapshots", "credit_disputes", "money_wins", "sell_items", "owed_to_me", "no_spend_days",
                 "money_settings", "money_targets")


def export(conn: Connection, org: str) -> dict:
    """Everything you've entered in Money, as JSON (your organization id left out)."""
    out = {}
    for name in EXPORT_TABLES:
        t = db.metadata.tables[name]
        rows = conn.execute(select(t).where(t.c.organization_id == org)).fetchall()
        out[name] = [{k: (str(v) if isinstance(v, (date, datetime)) else v) for k, v in r._mapping.items()
                      if k not in ("organization_id", "created_by")} for r in rows]
    return {"exported_at": _now().isoformat(), "tables": out}


def setup(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    T = db.money_targets
    from .money2 import settings as s2
    accts = accounts(conn, org)
    steps = [
        ("pay", "Add when you get paid", bool(schedules(conn, org, tz))),
        ("bills", "Add your bills", bool(bills(conn, org, tz))),
        ("balance", "Add your checking balance", any(a["balance"] is not None for a in accts if a["kind"] in ("checking", "cash"))),
        ("cards", "Add your credit cards (nicknames only)", bool(credit(conn, org, tz)["cards"])),
        ("savings", "Make a savings goal", bool(goals(conn, org, tz))),
        ("emergency", "Pick your emergency fund", bool(s2(conn, org)["emergency_goal_id"])),
        ("income_goal", "Set a monthly income goal", bool(conn.execute(select(T.c.monthly_income_cents).where(
            T.c.organization_id == org, T.c.monthly_income_cents.is_not(None))).first())),
        ("reports", "Check your free credit reports", not all(b["due"] for b in credit_watch(conn, org, tz)["bureaus"])),
    ]
    done = sum(1 for s in steps if s[2])
    return {"steps": [{"key": k, "title": t, "done": d} for k, t, d in steps], "done": done, "total": len(steps)}


def on_time_rate(conn: Connection, org: str, tz: str | None = "UTC") -> float | None:
    return on_time(conn, org, tz)["on_time_rate"]
