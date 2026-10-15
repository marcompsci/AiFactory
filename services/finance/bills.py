"""Bills: reminders that are never skipped, payment proposals that are never auto-paid (THREAT_MODEL F14)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.logistics import service as logistics
from services.management.hierarchy import agent_by_key, submit_report
from services.management.pipeline import create_mission

from . import approvals as A
from . import audit
from .events import femit

BANK = "central-bank"


def reminder_window() -> timedelta:
    return timedelta(days=float(os.environ.get("AICIV_FINANCE_BILL_REMINDER_DAYS", "7")))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def tick(enqueue: Callable[[str], None]) -> int:
    acted = 0
    later: list[str] = []
    with transaction() as conn:
        now = _now()
        bm = agent_by_key(conn, "bill_manager")
        for b in conn.execute(select(db.bills).where(db.bills.c.status.in_(["UPCOMING", "DUE", "OVERDUE"]))).fetchall():
            due = datetime.fromisoformat(b.due_at)
            if due < now and b.status != "OVERDUE":
                conn.execute(update(db.bills).where(db.bills.c.id == b.id).values(status="OVERDUE"))
                audit.record(conn, org_id=b.organization_id, actor_type="agent", actor_id=bm.id, action="bill.overdue",
                             subject_type="bill", subject_id=b.id, detail={"payee": b.payee, "due_at": b.due_at})
                submit_report(conn, org_id=b.organization_id, agent_id=bm.id, kind="blocker", body="A bill is past due and needs the owner.")
                acted += 1
            elif due - now <= reminder_window() and b.status == "UPCOMING":
                conn.execute(update(db.bills).where(db.bills.c.id == b.id).values(status="DUE"))
            if due - now <= reminder_window() and not b.reminded_at:
                logistics.create_package(conn, org_id=b.organization_id, package_type="bill_reminder", origin=BANK, destination="owners-tower",
                                         priority=2, carrier_agent_id=bm.id, subject_type="bill", subject_id=b.id)
                conn.execute(update(db.bills).where(db.bills.c.id == b.id).values(reminded_at=db.utcnow()))
                femit(conn, "finance.bill_reminder", {"bill_id": b.id, "status": "OVERDUE" if due < now else "DUE", "data_mode": b.data_mode,
                                                      "label": "bill due soon" if due >= now else "bill overdue"},
                      agent_id=bm.id, simulated=b.data_mode == "simulated")
                if not b.autopay:
                    _propose_payment(conn, b, bm)
                acted += 1
        # Owner-approved bill payments: hand them to the Bill Manager (the tool re-checks the exact approval).
        for a in conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.action_type == "payment",
                                                                   db.financial_approvals.c.status == "APPROVED")).fetchall():
            if (a.details or {}).get("execution_mission_id"):
                continue
            mid = create_mission(conn, org_id=a.organization_id, kind="finance_execute", title="Pay an owner-approved bill",
                                 prompt="Execute exactly the approved payment; the tool refuses anything else.",
                                 params={"approval_id": a.id}, opportunity_id=None, created_by=bm.id)
            conn.execute(update(db.financial_approvals).where(db.financial_approvals.c.id == a.id)
                         .values(details={**(a.details or {}), "execution_mission_id": mid}))
            later.append(mid)
            acted += 1
        for a in conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.action_type == "payment",
                                                                   db.financial_approvals.c.status == "EXECUTED")).fetchall():
            bill_id = (a.details or {}).get("bill_id")
            if bill_id:
                conn.execute(update(db.bills).where(db.bills.c.id == bill_id, db.bills.c.status != "PAID").values(status="PAID"))
    for mid in later:
        enqueue(mid)
    return acted


def _propose_payment(conn, b, bm) -> str:
    acct = conn.execute(select(db.financial_accounts).where(db.financial_accounts.c.organization_id == b.organization_id,
                                                            db.financial_accounts.c.account_type == "checking",
                                                            db.financial_accounts.c.data_mode == b.data_mode)).first()
    ref, label = (f"acct:{acct.id}", f"{acct.name} ••{acct.mask}") if acct else ("owner-chooses", "You choose the payment method")
    aid = A.request(conn, org_id=b.organization_id, packet_id=None, action_type="payment", amount_minor=b.amount_minor, currency=b.currency,
                    recipient=b.payee, account_ref=ref, details={"bill_id": b.id, "due_at": b.due_at, "account_label": label},
                    requested_by_agent_id=bm.id, data_mode=b.data_mode)
    logistics.create_package(conn, org_id=b.organization_id, package_type="payment_proposal", origin=BANK, destination="owners-tower",
                             priority=2, carrier_agent_id=bm.id, subject_type="financial_approval", subject_id=aid)
    return aid
