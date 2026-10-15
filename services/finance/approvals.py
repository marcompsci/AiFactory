"""The financial approval engine (THREAT_MODEL F1-F5).

An approval is for one exact action: action type, amount in minor units, currency, recipient, funding account and
cost review packet, all bound by `payload_hash`. It expires. The owner decides it, and approving needs a fresh
step-up token for that approval. It is checked again, inside the transaction that executes it. It can be executed once.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from services.core import db

from . import audit
from . import packets as P
from .events import femit
from .permissions import APPROVAL_ACTIONS
from .stepup import StepUpRequired, check_token


class ApprovalRefused(PermissionError):
    pass


def ttl() -> timedelta:
    return timedelta(hours=float(os.environ.get("AICIV_FINANCE_APPROVAL_TTL_HOURS", "72")))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(*, org_id: str, packet_id: str | None, action_type: str, amount_minor: int, currency: str, recipient: str,
                 account_ref: str) -> str:
    body = json.dumps({"org": org_id, "packet": packet_id, "action": action_type, "amount_minor": int(amount_minor),
                       "currency": currency.upper(), "recipient": recipient, "account_ref": account_ref}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def request(conn: Connection, *, org_id: str, packet_id: str | None, action_type: str, amount_minor: int, currency: str,
            recipient: str, account_ref: str, details: dict, requested_by_agent_id: str | None, data_mode: str) -> str:
    if action_type not in APPROVAL_ACTIONS:
        raise ApprovalRefused(f"unknown financial action {action_type}")
    if amount_minor < 0:
        raise ApprovalRefused("amount cannot be negative")
    aid = db.new_id()
    h = payload_hash(org_id=org_id, packet_id=packet_id, action_type=action_type, amount_minor=amount_minor, currency=currency,
                     recipient=recipient, account_ref=account_ref)
    conn.execute(insert(db.financial_approvals).values(
        id=aid, organization_id=org_id, packet_id=packet_id, action_type=action_type, amount_minor=int(amount_minor),
        currency=currency.upper(), recipient=recipient, account_ref=account_ref, details=details, payload_hash=h, status="REQUESTED",
        requested_by_agent_id=requested_by_agent_id, expires_at=(_now() + ttl()).isoformat(), data_mode=data_mode))
    audit.record(conn, org_id=org_id, actor_type="agent" if requested_by_agent_id else "system", actor_id=requested_by_agent_id,
                 action="approval.requested", subject_type="financial_approval", subject_id=aid,
                 detail={"packet_id": packet_id, "action_type": action_type, "amount_minor": amount_minor, "currency": currency,
                         "recipient": recipient, "account_ref": account_ref, "payload_hash": h})
    return aid


def get(conn: Connection, approval_id: str):
    return conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.id == approval_id)).first()


def _expired(a) -> bool:
    return datetime.fromisoformat(a.expires_at) <= _now()


def _set(conn: Connection, a, status: str, *, actor_type: str, actor_id: str | None, reason: str, **values) -> None:
    conn.execute(update(db.financial_approvals).where(db.financial_approvals.c.id == a.id).values(status=status, **values))
    audit.record(conn, org_id=a.organization_id, actor_type=actor_type, actor_id=actor_id, action=f"approval.{status.lower()}",
                 subject_type="financial_approval", subject_id=a.id, detail={"from": a.status, "reason": reason})


def expire_if_needed(conn: Connection, a) -> bool:
    if a.status in ("REQUESTED", "APPROVED") and _expired(a):
        _set(conn, a, "EXPIRED", actor_type="system", actor_id=None, reason="past its expiry time")
        femit(conn, "finance.approval_expired", {"approval_id": a.id, "packet_id": a.packet_id, "action_type": a.action_type,
                                                 "data_mode": a.data_mode}, simulated=a.data_mode == "simulated")
        return True
    return False


def _current_terms_hash(conn: Connection, a) -> str:
    """Recompute from the packet's *current* option, so a packet edited after the request no longer matches."""
    opt = (a.details or {}).get("option")
    pkt = P.get(conn, a.packet_id) if a.packet_id else None
    if pkt is not None and opt:
        rec = (pkt.recommendation or {}).get("options", {}).get(opt)
        if rec is None:
            return "option-missing"
        return payload_hash(org_id=a.organization_id, packet_id=a.packet_id, action_type=a.action_type, amount_minor=rec["amount_minor"],
                            currency=rec["currency"], recipient=rec["recipient"], account_ref=rec["account_ref"])
    bill_id = (a.details or {}).get("bill_id")
    if bill_id:
        b = conn.execute(select(db.bills).where(db.bills.c.id == bill_id)).first()
        if b is None or b.status == "PAID":
            return "bill-missing-or-paid"
        return payload_hash(org_id=a.organization_id, packet_id=None, action_type=a.action_type, amount_minor=b.amount_minor,
                            currency=b.currency, recipient=b.payee, account_ref=a.account_ref)
    return payload_hash(org_id=a.organization_id, packet_id=a.packet_id, action_type=a.action_type, amount_minor=a.amount_minor,
                        currency=a.currency, recipient=a.recipient, account_ref=a.account_ref)


DECISIONS = ("APPROVE", "REJECT", "DEFER", "MORE_RESEARCH")


def decide(conn: Connection, *, approval_id: str, decision: str, presented_hash: str, owner_id: str, owner_role: str,
           step_up_token: str | None = None, mfa_fresh: bool = False, note: str | None = None) -> dict:
    """The owner's decision. Refuses anything stale, modified, expired or not authenticated strongly enough."""
    a = get(conn, approval_id)
    if a is None:
        raise ApprovalRefused("unknown approval")
    if owner_role != "owner":
        raise ApprovalRefused("only the owner can decide financial approvals")
    if decision not in DECISIONS:
        raise ApprovalRefused(f"decision must be one of {', '.join(DECISIONS)}")
    if a.status != "REQUESTED":
        raise ApprovalRefused(f"this approval is {a.status.lower()}; it cannot be decided again")
    if expire_if_needed(conn, a):
        raise ApprovalRefused("this approval expired; ask the bank for a fresh one")
    if presented_hash != a.payload_hash:
        raise ApprovalRefused("what you reviewed is not what is on record (stale or modified request)")
    if _current_terms_hash(conn, a) != a.payload_hash:
        _set(conn, a, "INVALIDATED", actor_type="system", actor_id=None, reason="the underlying request changed after approval was requested")
        raise ApprovalRefused("the request changed after it was sent to you; it has been invalidated")
    method = None
    if decision == "APPROVE":
        if mfa_fresh:
            method = "supabase_aal2"
        else:
            try:
                method = check_token(step_up_token, user_id=owner_id, purpose=approval_id)
            except StepUpRequired as exc:
                raise ApprovalRefused(f"step-up verification required: {exc}") from exc
    status = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "DEFER": "DEFERRED", "MORE_RESEARCH": "MORE_RESEARCH"}[decision]
    _set(conn, a, status, actor_type="owner", actor_id=owner_id, reason=(note or decision.lower())[:300],
         decided_by=owner_id, decided_role=owner_role, decided_at=db.utcnow(), step_up_method=method)
    femit(conn, "finance.approval_decided", {"approval_id": a.id, "packet_id": a.packet_id, "decision": decision,
                                             "action_type": a.action_type, "data_mode": a.data_mode}, simulated=a.data_mode == "simulated")
    # Sibling options for the same packet can no longer be chosen once one is decided.
    for other in conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.packet_id == a.packet_id,
                                                                   db.financial_approvals.c.id != a.id,
                                                                   db.financial_approvals.c.status == "REQUESTED")).fetchall():
        _set(conn, other, "INVALIDATED", actor_type="system", actor_id=None, reason=f"owner decided option {approval_id}")
    return {"approval_id": a.id, "status": status, "step_up_method": method}


def authorize_execution(conn: Connection, *, org_id: str, approval_id: str, action_type: str, amount_minor: int, currency: str,
                        recipient: str, account_ref: str) -> object:
    """Called at the tool boundary, inside the transaction that records the execution (THREAT_MODEL F4)."""
    a = get(conn, approval_id)
    if a is None or a.organization_id != org_id:
        raise ApprovalRefused("no such approval for this organization")
    if a.status == "EXECUTED":
        raise ApprovalRefused("this approval was already used")
    if a.status != "APPROVED":
        raise ApprovalRefused(f"approval is {a.status.lower()}, not approved by the owner")
    if a.decided_role != "owner" or not a.decided_by or not a.step_up_method:
        raise ApprovalRefused("approval lacks an owner decision with step-up verification")
    if _expired(a):
        raise ApprovalRefused("approval expired before execution")
    asked = payload_hash(org_id=org_id, packet_id=a.packet_id, action_type=action_type, amount_minor=amount_minor, currency=currency,
                         recipient=recipient, account_ref=account_ref)
    if asked != a.payload_hash:
        raise ApprovalRefused("requested action differs from what the owner approved (amount, recipient, account or type)")
    if _current_terms_hash(conn, a) != a.payload_hash:
        raise ApprovalRefused("the underlying request changed after the owner approved it")
    if a.action_type == "tax_filing":
        raise ApprovalRefused("no authorized tax-filing integration is configured; filings are never submitted from here")
    if a.action_type in ("official_submission", "financial_publication", "transfer", "banking_change") and a.data_mode != "simulated":
        raise ApprovalRefused(f"no authorized integration for {a.action_type.replace('_', ' ')}; complete it yourself")
    return a


def mark_executed(conn: Connection, a, *, execution_ref: str, execution_mode: str, actor_type: str, actor_id: str | None) -> bool:
    """Compare-and-swap so an approval can only ever be executed once, even under concurrency."""
    res = conn.execute(update(db.financial_approvals).where(db.financial_approvals.c.id == a.id, db.financial_approvals.c.status == "APPROVED")
                       .values(status="EXECUTED", executed_at=db.utcnow(), execution_ref=execution_ref, execution_mode=execution_mode))
    if res.rowcount != 1:
        return False
    audit.record(conn, org_id=a.organization_id, actor_type=actor_type, actor_id=actor_id, action="approval.executed",
                 subject_type="financial_approval", subject_id=a.id, detail={"execution_ref": execution_ref, "execution_mode": execution_mode})
    return True
