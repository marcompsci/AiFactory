"""The fee review workflow (spec §6, §12), advanced by the durable scheduler like the V4 pipeline.

SUBMITTED ─purchase_request / expense_alert arrives at the bank─▶ AT_BANK (CFO receives and classifies it)
AT_BANK ─fee_research_request to the Research Observatory─▶ RESEARCH_REQUESTED ─received─▶ RESEARCHING (a Haiku researcher's mission)
RESEARCHING ─savings_recommendation back to the bank─▶ FINDINGS_RETURNED (Savings Strategist and CFO analysis mission)
FINDINGS_RETURNED ─significant: to the General Manager─▶ GM_REVIEW ─owner_approval_request─▶ OWNER_DECISION
                  └─routine: straight to the Owner's Tower─────────────────────────────────────▶ OWNER_DECISION
OWNER_DECISION ─approve (step-up)─▶ APPROVED ─execution mission, re-checked at the tool─▶ EXECUTED
               ├─reject─▶ REJECTED   ├─defer─▶ DEFERRED   └─more research─▶ RESEARCH_REQUESTED

Every step reads the database, does at most one thing, and writes its result. A stage only starts when its package
has physically ARRIVED at the right building. Nothing here buys, pays, cancels or files anything.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.logistics import service as logistics
from services.management.hierarchy import agent_by_key, general_manager, submit_report
from services.management.pipeline import _greet, _mission, create_mission

from . import approvals as A
from . import audit
from . import packets as P
from .events import femit
from .redaction import for_model

log = logging.getLogger("aiciv.finance")
ACTIVE = ("SUBMITTED", "AT_BANK", "RESEARCH_REQUESTED", "RESEARCHING", "FINDINGS_RETURNED", "GM_REVIEW", "OWNER_DECISION", "APPROVED", "DEFERRED")
DONE = ("COMPLETED", "FAILED", "CANCELLED")
MAX_RESEARCH_ROUNDS = 3
BANK = "central-bank"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pkg(conn, packet_id: str, ptype: str):
    return conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.subject_id == packet_id,
                                                            db.logistics_packages.c.package_type == ptype)
                        .order_by(db.logistics_packages.c.created_at.desc())).first()


def _ship(conn, p, ptype: str, origin: str, destination: str, carrier=None, priority: int = 4) -> str:
    return logistics.create_package(conn, org_id=p.organization_id, package_type=ptype, origin=origin, destination=destination,
                                    priority=priority, carrier_agent_id=carrier.id if carrier else None,
                                    subject_type="cost_review_packet", subject_id=p.id)


def _approvals(conn, packet_id: str) -> list:
    return conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.packet_id == packet_id)
                        .order_by(db.financial_approvals.c.created_at)).fetchall()


def _invalidate_open(conn, packet_id: str, reason: str) -> None:
    for a in _approvals(conn, packet_id):
        if a.status in ("REQUESTED", "APPROVED"):
            A._set(conn, a, "INVALIDATED", actor_type="system", actor_id=None, reason=reason)


class FinancePipeline:
    def __init__(self, enqueue: Callable[[str], None], gateway=None) -> None:
        self.enqueue = enqueue
        self.gateway = gateway
        from .investigations import InvestigationPipeline

        self.investigations = InvestigationPipeline(enqueue, gateway)

    # ------------------------------------------------------------------ scheduler entry
    def tick(self) -> dict:
        out = {"packets": 0, "expired": 0, "bills": 0, "investigations": 0}
        try:
            out["investigations"] = self.investigations.tick()
        except Exception:
            log.exception("investigation tick failed")
        with db.get_engine().connect() as conn:
            ids = [r.id for r in conn.execute(select(db.cost_review_packets.c.id).where(db.cost_review_packets.c.status.in_(ACTIVE)))]
        for pid in ids:
            try:
                out["packets"] += self.step(pid)
            except Exception:  # one bad packet never stalls the others
                log.exception("finance step failed for %s", pid)
        try:
            out["expired"] = self.expire()
            from .bills import tick as bills_tick
            out["bills"] = bills_tick(self.enqueue)
        except Exception:
            log.exception("finance housekeeping failed")
        return out

    def step(self, pid: str) -> int:
        later: list[str] = []
        with transaction() as conn:
            p = P.get(conn, pid)
            fn = getattr(self, f"_{p.status.lower()}", None)
            acted = fn(conn, p, later) if fn else 0
        for item in later:
            if item.startswith("gm:"):
                self.gm_review(item[3:])
            else:
                self.enqueue(item)
        return acted or 0

    # ------------------------------------------------------------------ stages
    def _submitted(self, conn, p, q) -> int:
        pkg = _pkg(conn, p.id, "purchase_request") or _pkg(conn, p.id, "expense_alert")
        if pkg is None and p.origin == "fee_detected":
            _ship(conn, p, "expense_alert", BANK, BANK, agent_by_key(conn, "expense_auditor"))
            return 1
        if pkg is None or pkg.status != "ARRIVED":
            return 0
        cfo = agent_by_key(conn, "cfo")
        _greet(conn, cfo, BANK)
        logistics.receive(conn, pkg.id, cfo.id)
        P.set_status(conn, p.id, "AT_BANK", "received at the AI Central Bank", agent_id=cfo.id)
        return 1

    def _at_bank(self, conn, p, q) -> int:
        cfo = agent_by_key(conn, "cfo")
        if p.classification == "legally_required":
            # Obligations are paid, not shopped around (spec §6: do not evade).
            return self._start_analysis(conn, p, q, "legal obligation: no alternatives sought")
        _ship(conn, p, "fee_research_request", BANK, "data-observatory", cfo)
        P.set_status(conn, p.id, "RESEARCH_REQUESTED", "sent to the Research Division", agent_id=cfo.id)
        return 1

    def _research_requested(self, conn, p, q) -> int:
        pkg = _pkg(conn, p.id, "fee_research_request")
        if pkg is None or pkg.status not in ("ARRIVED", "RECEIVED"):
            return 0
        lead = agent_by_key(conn, "researcher")
        if pkg.status == "ARRIVED":
            _greet(conn, lead, "data-observatory")
            logistics.receive(conn, pkg.id, lead.id)
        researcher = "research_apps" if (p.research_rounds or 0) % 2 == 0 else "research_marketplaces"
        mid = create_mission(conn, org_id=p.organization_id, kind="cost_research", title="Research alternatives for a cost review",
                             prompt="Find legitimate alternatives from authorized sources and compare them.",
                             params={"packet_id": p.id, "agent_key": researcher}, opportunity_id=None, created_by=lead.id)
        # a new research round means a fresh General Manager review later (the earlier one stays in the audit log)
        P.set_status(conn, p.id, "RESEARCHING", "research mission started", agent_id=lead.id, research_mission_id=mid, gm_decision={})
        q.append(mid)
        return 1

    def _researching(self, conn, p, q) -> int:
        m = _mission(conn, p.research_mission_id)
        if m is None or m.status not in DONE:
            return 0
        pkg = _pkg(conn, p.id, "savings_recommendation")
        if pkg is None or (pkg.created_at or "") < (m.created_at or ""):
            if m.status != "COMPLETED":
                submit_report(conn, org_id=p.organization_id, agent_id=agent_by_key(conn, "researcher").id, kind="blocker",
                              body="Cost research did not complete; the bank will decide with what it has.")
            researcher = agent_by_key(conn, (m.params or {}).get("agent_key", "research_apps"))
            _ship(conn, p, "savings_recommendation", "data-observatory", BANK, researcher)
            return 1
        if pkg.status != "ARRIVED":
            return 0
        strat = agent_by_key(conn, "savings_strategist")
        _greet(conn, strat, BANK)
        logistics.receive(conn, pkg.id, strat.id)
        femit(conn, "finance.findings_returned", {"packet_id": p.id, "data_mode": p.data_mode, "round": p.research_rounds},
              agent_id=strat.id, simulated=p.data_mode == "simulated")
        return self._start_analysis(conn, p, q, "findings received by the Savings Strategist")

    def _start_analysis(self, conn, p, q, why: str) -> int:
        cfo = agent_by_key(conn, "cfo")
        mid = create_mission(conn, org_id=p.organization_id, kind="cost_analysis", title="Analyze a cost review",
                             prompt="Compare the options and prepare exact approval requests for the owner.",
                             params={"packet_id": p.id}, opportunity_id=None, created_by=cfo.id)
        P.set_status(conn, p.id, "FINDINGS_RETURNED", why, agent_id=cfo.id, analysis_mission_id=mid)
        q.append(mid)
        return 1

    def _findings_returned(self, conn, p, q) -> int:
        m = _mission(conn, p.analysis_mission_id)
        if m is None or m.status not in DONE:
            return 0
        cfo = agent_by_key(conn, "cfo")
        if m.status != "COMPLETED":
            _invalidate_open(conn, p.id, "analysis did not complete")
            P.set_status(conn, p.id, "CLOSED", "analysis did not complete; nothing will be bought", agent_id=cfo.id)
            submit_report(conn, org_id=p.organization_id, agent_id=cfo.id, kind="blocker", body="A cost review could not be analyzed and was closed.")
            return 1
        femit(conn, "finance.recommendation_ready", {"packet_id": p.id, "significant": bool(p.significant), "data_mode": p.data_mode},
              agent_id=cfo.id, simulated=p.data_mode == "simulated")
        if p.significant:
            _ship(conn, p, "purchase_request" if p.origin == "purchase_request" else "expense_alert", BANK, "nexus-spire", cfo, priority=3)
            P.set_status(conn, p.id, "GM_REVIEW", "significant: escalated to the General Manager", agent_id=cfo.id)
        else:
            _ship(conn, p, "owner_approval_request", BANK, "owners-tower", cfo, priority=3)
            P.set_status(conn, p.id, "OWNER_DECISION", "routine: sent to the Owner's Tower", agent_id=cfo.id)
        return 1

    def _gm_review(self, conn, p, q) -> int:
        if p.gm_decision:
            return 0
        pkg = conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.subject_id == p.id,
                                                               db.logistics_packages.c.destination_district == "nexus-spire")
                           .order_by(db.logistics_packages.c.created_at.desc())).first()
        if pkg is None or pkg.status != "ARRIVED":
            return 0
        gm = general_manager(conn)
        _greet(conn, gm, "nexus-spire")
        logistics.receive(conn, pkg.id, gm.id)
        q.append(f"gm:{p.id}")
        return 1

    def gm_review(self, pid: str) -> None:
        """Rules first; Opus (when configured) may only tighten. The model call happens with no transaction open."""
        with db.get_engine().connect() as conn:
            p = P.get(conn, pid)
            if p is None or p.status != "GM_REVIEW" or p.gm_decision:
                return
            open_requests = [a for a in _approvals(conn, pid) if a.status == "REQUESTED"]
        outcome, reasons = "forward", []
        if p.origin == "purchase_request" and len((p.justification or "").strip()) < 10:
            outcome, reasons = "reject", ["no business justification was given"]
        elif not p.findings and p.classification != "legally_required" and (p.research_rounds or 0) < 2:
            outcome, reasons = "more_research", ["no alternatives were found; one more research round"]
        elif p.origin == "purchase_request" and not open_requests:
            outcome, reasons = "reject", ["no approvable option was prepared"]
        method, model, note = "rules", None, None
        if outcome == "forward" and self.gateway is not None and getattr(self.gateway, "available", False):
            from services.model_gateway.gateway import ModelRequest, ProviderError
            view = for_model(vendor=p.vendor, item=p.item, category=p.classification, amount_minor=p.amount_minor, interval=p.interval)
            try:
                with db.get_engine().connect() as conn:
                    gm_model = general_manager(conn).model_name
                res = self.gateway.complete(ModelRequest(
                    system="You are the General Manager of a small software company. You can only make spending decisions stricter.",
                    prompt="Should this recommendation go to the owner, or does it need more research first? Reply with one word, FORWARD or "
                           "RESEARCH, then one sentence why.\n<untrusted>"
                           + str({"request": view, "recommendation": (p.recommendation or {}).get("summary"),
                                  "classification": p.classification, "risk": p.risk}) + "</untrusted>",
                    max_tokens=120, model=gm_model), preferred_provider="anthropic")
                method, model, note = "model", res.model, res.text.strip()[:400]
                if note.upper().startswith("RESEARCH") and (p.research_rounds or 0) < MAX_RESEARCH_ROUNDS:
                    outcome, reasons = "more_research", ["the General Manager asked for more research"]
                with transaction() as conn:
                    from services.orchestrator import ops
                    ops.record_usage(conn, org_id=p.organization_id, mission_id=None, agent_id=general_manager(conn).id, provider=res.provider,
                                     model=res.model, input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                                     estimated_cost_usd=res.estimated_cost_usd)
            except ProviderError as exc:
                note = f"model unavailable ({exc.kind}); rules decision stands"
        with transaction() as conn:
            p = P.get(conn, pid)
            if p.status != "GM_REVIEW" or p.gm_decision:
                return
            gm = general_manager(conn)
            decision = {"outcome": outcome, "reasons": reasons, "method": method, "model": model, "note": note, "at": db.utcnow()}
            conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == pid).values(gm_decision=decision))
            audit.record(conn, org_id=p.organization_id, actor_type="agent", actor_id=gm.id, action="gm.reviewed",
                         subject_type="cost_review_packet", subject_id=pid, detail={"outcome": outcome, "reasons": reasons, "method": method})
            femit(conn, "finance.gm_reviewed", {"packet_id": pid, "decision": outcome, "data_mode": p.data_mode}, agent_id=gm.id,
                  simulated=p.data_mode == "simulated")
            if outcome == "forward":
                _ship(conn, p, "owner_approval_request", "nexus-spire", "owners-tower", gm, priority=2)
                P.set_status(conn, pid, "OWNER_DECISION", "General Manager forwarded it to the owner", agent_id=gm.id)
            elif outcome == "more_research":
                _invalidate_open(conn, pid, "General Manager asked for more research")
                conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == pid).values(gm_decision={}))
                _ship(conn, p, "fee_research_request", "nexus-spire", "data-observatory", gm)
                P.set_status(conn, pid, "RESEARCH_REQUESTED", "General Manager asked for more research", agent_id=gm.id)
            else:
                _invalidate_open(conn, pid, "General Manager rejected the request")
                P.set_status(conn, pid, "REJECTED", "General Manager rejected the request", agent_id=gm.id)

    def _owner_decision(self, conn, p, q) -> int:
        pkg = _pkg(conn, p.id, "owner_approval_request")
        if pkg is None or pkg.status != "ARRIVED":
            return 0
        logistics.receive(conn, pkg.id, None)
        femit(conn, "finance.approval_requested", {"packet_id": p.id, "origin": p.origin, "data_mode": p.data_mode,
                                                   "label": "cost review waiting for the owner"}, simulated=p.data_mode == "simulated")
        return 1

    def _approved(self, conn, p, q) -> int:
        approved = next((a for a in _approvals(conn, p.id) if a.status in ("APPROVED", "EXECUTED")), None)
        if approved is None:
            return 0
        if approved.status == "EXECUTED":
            P.set_status(conn, p.id, "EXECUTED", "owner-approved action carried out", agent_id=agent_by_key(conn, "bill_manager").id)
            return 1
        if p.execution_mission_id is None:
            bm = agent_by_key(conn, "bill_manager")
            mid = create_mission(conn, org_id=p.organization_id, kind="finance_execute", title="Carry out an owner-approved action",
                                 prompt="Execute exactly the approved action; the tool refuses anything else.",
                                 params={"packet_id": p.id, "approval_id": approved.id}, opportunity_id=None, created_by=bm.id)
            conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == p.id).values(execution_mission_id=mid))
            q.append(mid)
            return 1
        return 0

    def _deferred(self, conn, p, q) -> int:
        if p.deferred_until and datetime.fromisoformat(p.deferred_until) <= _now():
            reopen(conn, p.id, actor_type="system", actor_id=None, reason="deferral period ended")
            return 1
        return 0

    # ------------------------------------------------------------------ housekeeping
    def expire(self) -> int:
        n = 0
        with transaction() as conn:
            for a in conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.status.in_(["REQUESTED", "APPROVED"]))).fetchall():
                if A.expire_if_needed(conn, a):
                    n += 1
                    if a.packet_id:
                        p = P.get(conn, a.packet_id)
                        live = [x for x in _approvals(conn, a.packet_id) if x.status in ("REQUESTED", "APPROVED", "EXECUTED")]
                        from .investigations import is_investigating
                        # while the owner's investigation runs, the request stays pending; fresh approvals follow it
                        if p.status in ("OWNER_DECISION", "APPROVED") and not live and not is_investigating(conn, p.id):
                            P.set_status(conn, p.id, "DEFERRED", "approval expired; reopen to get a fresh one")
        return n


def reopen(conn, packet_id: str, *, actor_type: str, actor_id: str | None, reason: str) -> None:
    """Fresh approval requests (new expiry, same exact terms as the recorded options) and a new trip to the tower."""
    p = P.get(conn, packet_id)
    if p.status != "DEFERRED":
        raise A.ApprovalRefused("only deferred cost reviews can be reopened")
    for key, o in ((p.recommendation or {}).get("options") or {}).items():
        A.request(conn, org_id=p.organization_id, packet_id=p.id, action_type="purchase", amount_minor=o["amount_minor"], currency=o["currency"],
                  recipient=o["recipient"], account_ref=o["account_ref"],
                  details={"option": key, "item": o["item"], "interval": o["interval"], "account_label": o.get("account_label")},
                  requested_by_agent_id=agent_by_key(conn, "cfo").id, data_mode=p.data_mode)
    conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == packet_id).values(deferred_until=None))
    _ship(conn, p, "owner_approval_request", BANK, "owners-tower", agent_by_key(conn, "cfo"), priority=3)
    P.set_status(conn, packet_id, "OWNER_DECISION", reason, actor_type=actor_type, actor_id=actor_id)


def owner_decision(conn, *, packet_id: str, approval_id: str | None, decision: str, presented_hash: str | None, owner_id: str,
                   owner_role: str, step_up_token: str | None, mfa_fresh: bool, note: str | None, defer_days: int | None) -> dict:
    """The owner's call on a cost review, from the Owner's Tower."""
    p = P.get(conn, packet_id)
    if p is None:
        raise A.ApprovalRefused("unknown cost review")
    if owner_role != "owner":
        raise A.ApprovalRefused("only the owner can decide cost reviews")
    if p.status != "OWNER_DECISION":
        raise A.ApprovalRefused(f"this cost review is {p.status.lower().replace('_', ' ')}, not waiting for you")
    from . import investigations as INV

    if decision == "RESEARCH_FREE_ALTERNATIVE":
        # Research and sandboxed evaluation only: the request and its approval requests stay exactly as they are.
        inv_id = INV.start(conn, packet_id=packet_id, owner_id=owner_id, owner_role=owner_role, note=note)
        return {"packet_id": packet_id, "decision": decision, "investigation_id": inv_id, "request_status": "PENDING_OWNER_DECISION",
                "authorizes": "research and sandboxed evaluation only"}
    running = INV.active_for(conn, packet_id)
    open_reqs = [a for a in _approvals(conn, packet_id) if a.status == "REQUESTED"]
    result: dict = {"packet_id": packet_id, "decision": decision}
    if approval_id:
        if approval_id not in {a.id for a in open_reqs}:
            raise A.ApprovalRefused("that approval is not open on this cost review")
        result.update(A.decide(conn, approval_id=approval_id, decision=decision, presented_hash=presented_hash or "", owner_id=owner_id,
                               owner_role=owner_role, step_up_token=step_up_token, mfa_fresh=mfa_fresh, note=note))
    elif decision == "APPROVE":
        raise A.ApprovalRefused("choose which option to approve")
    else:
        for a in open_reqs:  # rejecting / deferring / more research applies to every open option
            A._set(conn, a, {"REJECT": "REJECTED", "DEFER": "DEFERRED", "MORE_RESEARCH": "MORE_RESEARCH", "ACKNOWLEDGE": "INVALIDATED"}.get(decision, "INVALIDATED"),
                   actor_type="owner", actor_id=owner_id, reason=(note or decision.lower())[:300], decided_by=owner_id, decided_role=owner_role,
                   decided_at=db.utcnow())
    conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == packet_id).values(owner_note=(note or None)))
    if running is not None:
        INV.cancel(conn, running.id, reason=f"owner decided ({decision.lower()}) before the investigation finished", actor_type="owner",
                   actor_id=owner_id)
    if decision == "APPROVE":
        P.set_status(conn, packet_id, "APPROVED", "owner approved (step-up verified)", actor_type="owner", actor_id=owner_id)
    elif decision == "REJECT":
        P.set_status(conn, packet_id, "REJECTED", "owner rejected", actor_type="owner", actor_id=owner_id)
    elif decision == "DEFER":
        until = (_now() + timedelta(days=max(1, min(int(defer_days or 7), 90)))).isoformat()
        P.set_status(conn, packet_id, "DEFERRED", "owner deferred", actor_type="owner", actor_id=owner_id, deferred_until=until)
    elif decision == "MORE_RESEARCH":
        if (p.research_rounds or 0) >= MAX_RESEARCH_ROUNDS:
            raise A.ApprovalRefused(f"already researched {p.research_rounds} times; approve, reject or defer")
        _ship(conn, p, "fee_research_request", "owners-tower", "data-observatory", None)
        P.set_status(conn, packet_id, "RESEARCH_REQUESTED", "owner asked for more research", actor_type="owner", actor_id=owner_id)
    elif decision == "ACKNOWLEDGE":
        if open_reqs:
            raise A.ApprovalRefused("this cost review has a purchase to decide; approve, reject, defer or ask for research")
        P.set_status(conn, packet_id, "CLOSED", "owner acknowledged the recommendation", actor_type="owner", actor_id=owner_id)
    else:
        raise A.ApprovalRefused("unknown decision")
    return result


def finance_mode(conn, org_id: str) -> str:
    """simulated unless the owner has authorized at least one live (or uploaded) connection."""
    live = conn.execute(select(db.financial_connections.c.id).where(db.financial_connections.c.organization_id == org_id,
                                                                    db.financial_connections.c.status == "ACTIVE",
                                                                    db.financial_connections.c.data_mode != "simulated")).first()
    return "live" if live else "simulated"

