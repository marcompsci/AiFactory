"""CostReviewPackets: one per requested purchase or detected fee. The authoritative record every financial package
on the conveyor points at."""
from __future__ import annotations

import os
import re

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from services.core import db

from . import audit
from .events import check_packet_transition, femit

LEGAL = re.compile(r"(?i)\b(irs|internal revenue|franchise tax|secretary of state|department of revenue|sales tax|use tax|payroll tax|"
                   r"business license|annual report fee|state filing|registered agent fee|withholding)\b")
AVOIDABLE_FEE = re.compile(r"(?i)\b(overdraft|maintenance fee|monthly service|foreign transaction|fx fee|wire fee|late fee|"
                           r"returned item|paper statement|atm fee|minimum balance)\b")


def significant_threshold_minor() -> int:
    return int(float(os.environ.get("AICIV_FINANCE_SIGNIFICANT_USD", "100")) * 100)


def annualize(amount_minor: int, interval: str) -> int:
    return amount_minor * 12 if interval == "month" else amount_minor


def classify(*, vendor: str, item: str, interval: str, amount_minor: int, contract_terms: str | None = None,
             unusual: bool = False) -> dict:
    """Deterministic rules (THREAT_MODEL F8: no model needed for routine classification). Returns the classification,
    why, the annualized cost, whether it is significant, and the risk level."""
    text = f"{vendor} {item}"
    if LEGAL.search(text):
        cls, why = "legally_required", "matches a tax/government/regulatory obligation; it will be paid on time, not avoided"
    elif contract_terms or re.search(r"(?i)\b(contract|commitment|annual agreement|term)\b", item):
        cls, why = "contractual", f"under contract ({contract_terms or 'terms in the item description'}); changes only at the end of the term"
    elif AVOIDABLE_FEE.search(text):
        cls, why = "optional", "an avoidable account or transaction fee"
    elif interval in ("month", "year"):
        cls, why = "recurring", f"billed every {interval}"
    else:
        cls, why = "one_time", "a single charge"
    yearly = annualize(amount_minor, interval)
    risk = "high" if (yearly >= 100_000 or cls == "contractual" or unusual) else "medium" if yearly >= significant_threshold_minor() else "low"
    significant = yearly >= significant_threshold_minor() or cls in ("contractual", "legally_required") or risk == "high"
    if unusual:
        why += "; the amount is unusual for this payee"
    return {"classification": cls, "classification_reason": why, "annualized_minor": yearly, "significant": int(significant), "risk": risk}


def create(conn: Connection, *, org_id: str, origin: str, vendor: str, item: str, amount_minor: int, currency: str, interval: str,
           justification: str | None, requested_by_agent_id: str | None, request_mission_id: str | None,
           subject_type: str | None, subject_id: str | None, data_mode: str, contract_terms: str | None = None,
           unusual: bool = False) -> str:
    if amount_minor < 0 or amount_minor > 10_000_000:
        raise ValueError("amount must be between 0 and 100,000.00")
    if interval not in ("one_time", "month", "year"):
        raise ValueError("interval must be one_time, month or year")
    c = classify(vendor=vendor, item=item, interval=interval, amount_minor=amount_minor, contract_terms=contract_terms, unusual=unusual)
    pid = db.new_id()
    conn.execute(insert(db.cost_review_packets).values(
        id=pid, organization_id=org_id, origin=origin, status="SUBMITTED", requested_by_agent_id=requested_by_agent_id,
        request_mission_id=request_mission_id, subject_type=subject_type, subject_id=subject_id, vendor=vendor[:80], item=item[:120],
        justification=(justification or "")[:1000], amount_minor=amount_minor, currency=currency.upper()[:3], interval=interval,
        data_mode=data_mode, **c))
    audit.record(conn, org_id=org_id, actor_type="agent" if requested_by_agent_id else "system", actor_id=requested_by_agent_id,
                 action="packet.created", subject_type="cost_review_packet", subject_id=pid,
                 detail={"origin": origin, "vendor": vendor, "amount_minor": amount_minor, "interval": interval, **c})
    femit(conn, "finance.packet_created", {"packet_id": pid, "origin": origin, "classification": c["classification"],
                                           "significant": c["significant"], "risk": c["risk"], "data_mode": data_mode,
                                           "label": f"{origin.replace('_', ' ')}: {c['classification'].replace('_', ' ')}"},
          agent_id=requested_by_agent_id, mission_id=request_mission_id, simulated=data_mode == "simulated")
    return pid


def get(conn: Connection, packet_id: str):
    return conn.execute(select(db.cost_review_packets).where(db.cost_review_packets.c.id == packet_id)).first()


def set_status(conn: Connection, packet_id: str, target: str, reason: str, *, actor_type: str = "system", actor_id: str | None = None,
               agent_id: str | None = None, **values) -> None:
    p = get(conn, packet_id)
    if p.status == target and not values:
        return
    if p.status != target:
        check_packet_transition(p.status, target)
    conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == packet_id)
                 .values(status=target, updated_at=db.utcnow(), **values))
    audit.record(conn, org_id=p.organization_id, actor_type=actor_type, actor_id=actor_id, action="packet.status_changed",
                 subject_type="cost_review_packet", subject_id=packet_id, detail={"from": p.status, "to": target, "reason": reason})
    femit(conn, "finance.packet_status_changed", {"packet_id": packet_id, "from": p.status, "to": target, "origin": p.origin,
                                                  "data_mode": p.data_mode, "label": reason[:80]},
          agent_id=agent_id, simulated=p.data_mode == "simulated")
