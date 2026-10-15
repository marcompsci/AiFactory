"""V5.1 free-alternative investigations: owner-directed and read-only.

The owner's RESEARCH_FREE_ALTERNATIVE decision authorizes research and sandboxed evaluation, nothing else. The
cost review stays waiting for the owner (its approval requests are untouched), and the investigation runs as a
physical packet:

  REQUESTED     AI Central Bank ──savings_investigation──▶ Data Observatory   (Haiku researcher finds ≤ 5 candidates)
  RESEARCHING   Data Observatory ─────────────────────▶ AI Central Bank       (Savings Strategist scores, shortlists)
  EVALUATING    AI Central Bank ──────────────────────▶ Code Forge            (Developer tests the strongest in a sandbox)
  TESTING       Code Forge ───────────────────────────▶ Sentinel Citadel      (QA reviews the evidence)
                Sentinel Citadel ─────────────────────▶ Nexus Spire           (General Manager: recommendation only)
  MANAGER_REVIEW Nexus Spire ─────────────────────────▶ Owner's Tower
  AWAITING_OWNER                                                            (a new, explicit owner decision)
  + BLOCKED, FAILED, CANCELLED

The database is authoritative: a stage starts only when the backend has marked the right package ARRIVED. Every
transition is audited and published as a finance.* event without money in it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import transaction
from services.logistics import service as logistics
from services.management.hierarchy import agent_by_key, general_manager, submit_report
from services.management.pipeline import _greet, _mission, create_mission

from . import approvals as A
from . import audit
from . import packets as P
from .events import femit

log = logging.getLogger("aiciv.finance.investigations")

ACTIVE = ("REQUESTED", "RESEARCHING", "EVALUATING", "TESTING", "MANAGER_REVIEW")
TERMINAL = ("AWAITING_OWNER", "BLOCKED", "FAILED", "CANCELLED")
FLOW = {"REQUESTED": "RESEARCHING", "RESEARCHING": "EVALUATING", "EVALUATING": "TESTING", "TESTING": "MANAGER_REVIEW",
        "MANAGER_REVIEW": "AWAITING_OWNER"}
DONE = ("COMPLETED", "FAILED", "CANCELLED")
PKG = "savings_investigation"


class InvestigationRefused(PermissionError):
    pass


def get(conn: Connection, inv_id: str):
    return conn.execute(select(db.savings_investigations).where(db.savings_investigations.c.id == inv_id)).first()


def active_for(conn: Connection, packet_id: str):
    return conn.execute(select(db.savings_investigations).where(db.savings_investigations.c.packet_id == packet_id,
                                                               db.savings_investigations.c.status.in_(ACTIVE))).first()


def latest_for(conn: Connection, packet_id: str):
    return conn.execute(select(db.savings_investigations).where(db.savings_investigations.c.packet_id == packet_id)
                        .order_by(db.savings_investigations.c.created_at.desc())).first()


def check_transition(current: str, target: str) -> None:
    ok = FLOW.get(current) == target or (current in ACTIVE and target in ("BLOCKED", "FAILED", "CANCELLED")) \
        or (current == "BLOCKED" and target == "CANCELLED")
    if not ok:
        raise InvestigationRefused(f"investigation cannot go from {current} to {target}")


def set_status(conn: Connection, inv_id: str, target: str, reason: str, *, actor_type: str = "system", actor_id: str | None = None,
               agent_id: str | None = None, **values) -> None:
    inv = get(conn, inv_id)
    if inv.status == target:
        return
    check_transition(inv.status, target)
    if target in ("BLOCKED", "FAILED", "CANCELLED"):
        values["reason"] = reason[:500]
    conn.execute(update(db.savings_investigations).where(db.savings_investigations.c.id == inv_id)
                 .values(status=target, updated_at=db.utcnow(), **values))
    audit.record(conn, org_id=inv.organization_id, actor_type=actor_type, actor_id=actor_id, action="investigation.status_changed",
                 subject_type="savings_investigation", subject_id=inv_id, detail={"from": inv.status, "to": target, "reason": reason[:300]})
    femit(conn, "finance.investigation_status_changed", {"investigation_id": inv_id, "packet_id": inv.packet_id, "from": inv.status,
                                                         "to": target, "label": reason[:80], "data_mode": inv.data_mode},
          agent_id=agent_id, simulated=inv.data_mode == "simulated")


def start(conn: Connection, *, packet_id: str, owner_id: str, owner_role: str, note: str | None) -> str:
    """The owner's RESEARCH_FREE_ALTERNATIVE decision. Authorizes research and sandboxed evaluation only."""
    if owner_role != "owner":
        raise InvestigationRefused("only the owner can start an investigation")
    p = P.get(conn, packet_id)
    if p is None:
        raise InvestigationRefused("unknown cost review")
    if p.status != "OWNER_DECISION":
        raise InvestigationRefused(f"this cost review is {p.status.lower().replace('_', ' ')}, not waiting for you")
    if active_for(conn, packet_id):
        raise InvestigationRefused("an investigation is already running for this cost review")
    from .alt_research import category_for

    inv_id = db.new_id()
    conn.execute(db.savings_investigations.insert().values(
        id=inv_id, organization_id=p.organization_id, packet_id=packet_id, status="REQUESTED", requested_by=owner_id,
        owner_note=(note or "")[:500] or None, category=category_for(p.vendor, p.item), recommendation={}, data_mode=p.data_mode))
    audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=owner_id, action="investigation.requested",
                 subject_type="savings_investigation", subject_id=inv_id,
                 detail={"packet_id": packet_id, "authorizes": "research and sandboxed evaluation only",
                         "packet_status_preserved": "PENDING_OWNER_DECISION"})
    femit(conn, "finance.investigation_status_changed", {"investigation_id": inv_id, "packet_id": packet_id, "to": "REQUESTED",
                                                         "label": "owner asked for a free alternative", "data_mode": p.data_mode},
          simulated=p.data_mode == "simulated")
    logistics.create_package(conn, org_id=p.organization_id, package_type=PKG, origin="central-bank", destination="data-observatory",
                             priority=3, carrier_agent_id=agent_by_key(conn, "cfo").id, subject_type="savings_investigation", subject_id=inv_id)
    return inv_id


def cancel(conn: Connection, inv_id: str, *, reason: str, actor_type: str, actor_id: str | None) -> None:
    inv = get(conn, inv_id)
    if inv is None:
        raise InvestigationRefused("unknown investigation")
    if inv.status not in ACTIVE + ("BLOCKED",):
        raise InvestigationRefused(f"investigation is {inv.status.lower()}")
    set_status(conn, inv_id, "CANCELLED", reason, actor_type=actor_type, actor_id=actor_id)


def _leg(conn: Connection, inv_id: str, origin: str, destination: str):
    return conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.subject_id == inv_id,
                                                            db.logistics_packages.c.origin_district == origin,
                                                            db.logistics_packages.c.destination_district == destination)
                        .order_by(db.logistics_packages.c.created_at.desc())).first()


def _ship(conn: Connection, inv, origin: str, destination: str, carrier) -> None:
    if _leg(conn, inv.id, origin, destination) is None:
        logistics.create_package(conn, org_id=inv.organization_id, package_type=PKG, origin=origin, destination=destination, priority=3,
                                 carrier_agent_id=carrier.id if carrier else None, subject_type="savings_investigation", subject_id=inv.id)


def _arrived(conn: Connection, inv_id: str, origin: str, destination: str, receiver) -> bool:
    pkg = _leg(conn, inv_id, origin, destination)
    if pkg is None or pkg.status not in ("ARRIVED", "RECEIVED"):
        return False
    if pkg.status == "ARRIVED":
        if receiver is not None:
            _greet(conn, receiver, destination)
        logistics.receive(conn, pkg.id, receiver.id if receiver else None)
    return True


def _mission_for(conn: Connection, inv, kind: str, title: str, created_by, **params) -> str:
    return create_mission(conn, org_id=inv.organization_id, kind=kind, title=title,
                          prompt="Read-only investigation: research and sandboxed evaluation. No purchases, cancellations or deployments.",
                          params={"investigation_id": inv.id, "packet_id": inv.packet_id, **params}, opportunity_id=None, created_by=created_by.id)


class InvestigationPipeline:
    def __init__(self, enqueue: Callable[[str], None], gateway=None) -> None:
        self.enqueue = enqueue
        self.gateway = gateway

    def tick(self) -> int:
        with db.get_engine().connect() as conn:
            ids = [r.id for r in conn.execute(select(db.savings_investigations.c.id).where(db.savings_investigations.c.status.in_(ACTIVE)))]
        n = 0
        for inv_id in ids:
            try:
                n += self.step(inv_id)
            except Exception:  # one investigation never stalls the others
                log.exception("investigation step failed for %s", inv_id)
        return n

    def step(self, inv_id: str) -> int:
        later: list[str] = []
        with transaction() as conn:
            inv = get(conn, inv_id)
            fn = getattr(self, f"_{inv.status.lower()}", None)
            acted = fn(conn, inv, later) if fn else 0
        for item in later:
            if item.startswith("gm:"):
                self.manager_review(item[3:])
            else:
                self.enqueue(item)
        return acted or 0

    # ------------------------------------------------------------------ stages
    def _requested(self, conn, inv, q) -> int:
        lead = agent_by_key(conn, "researcher")
        if not _arrived(conn, inv.id, "central-bank", "data-observatory", lead):
            return 0
        mid = _mission_for(conn, inv, "alt_research", "Find free alternatives for a cost review", lead, agent_key="research_apps")
        set_status(conn, inv.id, "RESEARCHING", "research started at the Data Observatory", agent_id=lead.id, research_mission_id=mid)
        q.append(mid)
        return 1

    def _researching(self, conn, inv, q) -> int:
        m = _mission(conn, inv.research_mission_id)
        if m is None or m.status not in DONE:
            return 0
        if m.status != "COMPLETED":
            set_status(conn, inv.id, "FAILED", f"research mission {m.status.lower()}: {m.failure_reason or ''}")
            return 1
        n = conn.execute(select(db.alternative_candidates.c.id).where(db.alternative_candidates.c.investigation_id == inv.id)).fetchall()
        if not n:
            set_status(conn, inv.id, "BLOCKED", "no authorized source covers this tool yet; nothing was guessed")
            _ship(conn, inv, "data-observatory", "owners-tower", agent_by_key(conn, "researcher"))
            return 1
        _ship(conn, inv, "data-observatory", "central-bank", agent_by_key(conn, "research_apps"))
        strat = agent_by_key(conn, "savings_strategist")
        if not _arrived(conn, inv.id, "data-observatory", "central-bank", strat):
            return 0
        mid = _mission_for(conn, inv, "alt_evaluation", "Score free alternatives", strat)
        set_status(conn, inv.id, "EVALUATING", "shortlist returned to the AI Central Bank", agent_id=strat.id, evaluation_mission_id=mid)
        q.append(mid)
        return 1

    def _evaluating(self, conn, inv, q) -> int:
        m = _mission(conn, inv.evaluation_mission_id)
        if m is None or m.status not in DONE:
            return 0
        if m.status != "COMPLETED":
            set_status(conn, inv.id, "FAILED", f"evaluation mission {m.status.lower()}: {m.failure_reason or ''}")
            return 1
        _ship(conn, inv, "central-bank", "code-forge", agent_by_key(conn, "savings_strategist"))
        dev = agent_by_key(conn, "developer")
        if not _arrived(conn, inv.id, "central-bank", "code-forge", dev):
            return 0
        mid = _mission_for(conn, inv, "alt_sandbox", "Test the strongest free alternative in a sandbox", dev)
        set_status(conn, inv.id, "TESTING", "Code Forge is testing the strongest candidate in a disposable sandbox", agent_id=dev.id,
                   sandbox_mission_id=mid)
        q.append(mid)
        return 1

    def _testing(self, conn, inv, q) -> int:
        if inv.qa_mission_id is None:
            m = _mission(conn, inv.sandbox_mission_id)
            if m is None or m.status not in DONE:
                return 0
            ev = conn.execute(select(db.sandbox_evaluations.c.id).where(db.sandbox_evaluations.c.investigation_id == inv.id)).first()
            if m.status != "COMPLETED" and ev is None:
                set_status(conn, inv.id, "FAILED", f"sandbox mission {m.status.lower()} before recording any result: {m.failure_reason or ''}")
                return 1
            _ship(conn, inv, "code-forge", "sentinel-citadel", agent_by_key(conn, "developer"))
            qa = agent_by_key(conn, "qa")
            if not _arrived(conn, inv.id, "code-forge", "sentinel-citadel", qa):
                return 0
            mid = _mission_for(conn, inv, "alt_qa", "Review sandbox evidence for a free alternative", qa)
            conn.execute(update(db.savings_investigations).where(db.savings_investigations.c.id == inv.id).values(qa_mission_id=mid))
            q.append(mid)
            return 1
        m = _mission(conn, inv.qa_mission_id)
        if m is None or m.status not in DONE:
            return 0
        if m.status != "COMPLETED":
            set_status(conn, inv.id, "FAILED", f"QA review {m.status.lower()}: {m.failure_reason or ''}")
            return 1
        _ship(conn, inv, "sentinel-citadel", "nexus-spire", agent_by_key(conn, "qa"))
        gm = general_manager(conn)
        if not _arrived(conn, inv.id, "sentinel-citadel", "nexus-spire", gm):
            return 0
        set_status(conn, inv.id, "MANAGER_REVIEW", "evidence reached the General Manager", agent_id=gm.id)
        q.append(f"gm:{inv.id}")
        return 1

    def _manager_review(self, conn, inv, q) -> int:
        if not inv.recommendation:
            q.append(f"gm:{inv.id}")  # e.g. after a restart between receipt and review
            return 0
        _ship(conn, inv, "nexus-spire", "owners-tower", general_manager(conn))
        if not _arrived(conn, inv.id, "nexus-spire", "owners-tower", None):
            return 0
        refresh_approvals(conn, inv.packet_id)
        set_status(conn, inv.id, "AWAITING_OWNER", "recommendation delivered to the Owner's Tower")
        femit(conn, "finance.investigation_ready", {"investigation_id": inv.id, "packet_id": inv.packet_id, "data_mode": inv.data_mode,
                                                    "label": "free-alternative investigation ready"}, simulated=inv.data_mode == "simulated")
        femit(conn, "finance.approval_requested", {"packet_id": inv.packet_id, "data_mode": inv.data_mode,
                                                   "label": "investigation complete; your decision"}, simulated=inv.data_mode == "simulated")
        return 1

    def manager_review(self, inv_id: str) -> None:
        """The GM prepares an evidence-backed recommendation. It can recommend; it cannot authorize anything."""
        from .alt_research import manager_recommendation

        with db.get_engine().connect() as conn:
            inv = get(conn, inv_id)
            if inv is None or inv.status != "MANAGER_REVIEW" or inv.recommendation:
                return
            rec = manager_recommendation(conn, inv)
        note, model = None, None
        if self.gateway is not None and getattr(self.gateway, "available", False):
            from services.model_gateway.gateway import ModelRequest, ProviderError
            try:
                with db.get_engine().connect() as conn:
                    gm_model = general_manager(conn).model_name
                res = self.gateway.complete(ModelRequest(
                    system="You are the General Manager. You may explain a recommendation; you cannot approve spending or changes.",
                    prompt="In two sentences, explain this recommendation to the owner using only these facts.\n<untrusted>"
                           + str({k: rec[k] for k in ("headline", "options", "sandbox", "qa")}) + "</untrusted>", max_tokens=160, model=gm_model),
                    preferred_provider="anthropic")
                note, model = res.text.strip()[:500], res.model
            except ProviderError as exc:
                note = f"model unavailable ({exc.kind}); rules recommendation stands"
        rec = {**rec, "manager_note": note, "manager_model": model, "authorizes_transaction": False}
        with transaction() as conn:
            inv = get(conn, inv_id)
            if inv.status != "MANAGER_REVIEW" or inv.recommendation:
                return
            gm = general_manager(conn)
            conn.execute(update(db.savings_investigations).where(db.savings_investigations.c.id == inv_id).values(recommendation=rec))
            conn.execute(db.investigation_reviews.insert().values(
                id=db.new_id(), organization_id=inv.organization_id, investigation_id=inv_id, stage="manager", reviewer_agent_id=gm.id,
                verdict=rec["verdict"], summary=rec["headline"], findings=rec.get("findings", []), method="model" if model else "rules", model=model))
            audit.record(conn, org_id=inv.organization_id, actor_type="agent", actor_id=gm.id, action="investigation.manager_recommendation",
                         subject_type="savings_investigation", subject_id=inv_id, detail={"verdict": rec["verdict"], "authorizes_transaction": False})
            submit_report(conn, org_id=inv.organization_id, agent_id=gm.id, kind="completed_package",
                          body="Free-alternative investigation reviewed; recommendation is on its way to the owner.")


def refresh_approvals(conn: Connection, packet_id: str) -> None:
    """If the original request's approval requests expired during the investigation, issue fresh ones with the
    same exact terms, so the owner's final decision is on current, valid requests."""
    p = P.get(conn, packet_id)
    if p is None or p.status != "OWNER_DECISION":
        return
    live = conn.execute(select(db.financial_approvals.c.id).where(db.financial_approvals.c.packet_id == packet_id,
                                                                  db.financial_approvals.c.status == "REQUESTED")).fetchall()
    open_live = []
    for (aid,) in live:
        a = A.get(conn, aid)
        if not A.expire_if_needed(conn, a):
            open_live.append(aid)
    if open_live:
        return
    for key, o in ((p.recommendation or {}).get("options") or {}).items():
        A.request(conn, org_id=p.organization_id, packet_id=p.id, action_type="purchase", amount_minor=o["amount_minor"], currency=o["currency"],
                  recipient=o["recipient"], account_ref=o["account_ref"],
                  details={"option": key, "item": o["item"], "interval": o["interval"], "account_label": o.get("account_label")},
                  requested_by_agent_id=agent_by_key(conn, "cfo").id, data_mode=p.data_mode)


def is_investigating(conn: Connection, packet_id: str) -> bool:
    return active_for(conn, packet_id) is not None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
