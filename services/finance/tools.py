"""Financial tools. They go through the same registry as every other tool, so capability, task, project,
emergency-stop and audit checks apply. On top of that, `_check_finance` limits them to the finance department,
scopes them to the mission's packet, and gates execution on the owner's exact approval. Their arguments and
results never reach the event stream (THREAT_MODEL F7, F9)."""
from __future__ import annotations

from sqlalchemy import func, insert, select, update

from services.core import db
from services.core.events import transaction
from services.logistics import service as logistics
from services.tools.registry import ToolContext, ToolFailed, tool

from . import approvals as A
from . import audit
from . import packets as P
from . import research as R
from .events import femit
from .redaction import for_model


def _is_uuid(v: str) -> bool:
    import uuid

    try:
        uuid.UUID(v)
        return True
    except ValueError:
        return False


def _agent_district(conn, agent_id: str) -> str:
    return conn.execute(select(db.agent_positions.c.district).where(db.agent_positions.c.agent_id == agent_id)).scalar() or "nexus-spire"


@tool("request_purchase", description="Ask the AI Central Bank to review a paid tool or service. Reads no financial data; buys nothing.")
def request_purchase(ctx: ToolContext, vendor: str, item: str, amount_minor: int, interval: str, justification: str,
                     currency: str = "USD") -> dict:
    if not vendor.strip() or not item.strip():
        raise ToolFailed("vendor and item are required")
    with transaction() as conn:
        mode = conn.execute(select(db.missions.c.params).where(db.missions.c.id == ctx.mission_id)).scalar() or {}
        try:
            pid = P.create(conn, org_id=ctx.org_id, origin="purchase_request", vendor=vendor, item=item, amount_minor=int(amount_minor),
                           currency=currency, interval=interval, justification=justification, requested_by_agent_id=ctx.agent_id,
                           request_mission_id=ctx.mission_id, subject_type="tool_request", subject_id=None,
                           data_mode=mode.get("data_mode", "simulated"))
        except ValueError as exc:
            raise ToolFailed(str(exc)) from exc
        logistics.create_package(conn, org_id=ctx.org_id, package_type="purchase_request", origin=_agent_district(conn, ctx.agent_id),
                                 destination="central-bank", mission_id=ctx.mission_id, task_id=ctx.task_id, priority=4,
                                 carrier_agent_id=ctx.agent_id, subject_type="cost_review_packet", subject_id=pid)
    return {"packet_id": pid, "status": "SUBMITTED"}


@tool("research_cost_alternatives", finance=True,
      description="Research legitimate alternatives for one cost review, from authorized sources only (sees a redacted view).")
def research_cost_alternatives(ctx: ToolContext, packet_id: str) -> dict:
    with db.get_engine().connect() as conn:
        p = P.get(conn, packet_id)
    if p is None:
        raise ToolFailed("unknown cost review")
    view = for_model(vendor=p.vendor, item=p.item, category=None, amount_minor=p.amount_minor, interval=p.interval)
    out = R.research(vendor=p.vendor, item=p.item, amount_minor=p.amount_minor, interval=p.interval, classification=p.classification)
    with transaction() as conn:
        rounds = (P.get(conn, packet_id).research_rounds or 0) + 1
        conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == packet_id).values(
            findings=out["findings"], research_rounds=rounds, updated_at=db.utcnow()))
        audit.record(conn, org_id=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="research.completed",
                     subject_type="cost_review_packet", subject_id=packet_id,
                     detail={"round": rounds, "category": out["category"], "count": len(out["findings"]), "data_mode": out["data_mode"],
                             "note": out["note"]})
    return {"packet_id": packet_id, "count": len(out["findings"]), "data_mode": out["data_mode"], "note": out["note"],
            "category": out["category"], "redacted_view": view}


@tool("read_ledger_summary", finance=True, description="Aggregated spend by category over the last 90 days. No descriptions or accounts.")
def read_ledger_summary(ctx: ToolContext, category_key: str | None = None) -> dict:
    with db.get_engine().connect() as conn:
        q = (select(db.financial_transactions.c.category_key, func.count(), func.sum(db.financial_transactions.c.amount_minor))
             .where(db.financial_transactions.c.organization_id == ctx.org_id, db.financial_transactions.c.amount_minor < 0)
             .group_by(db.financial_transactions.c.category_key))
        if category_key:
            q = q.where(db.financial_transactions.c.category_key == category_key)
        rows = conn.execute(q).fetchall()
    return {"count": len(rows), "by_category": {r[0] or "uncategorized": {"transactions": r[1], "spend_minor": -int(r[2] or 0)} for r in rows}}


@tool("classify_cost", finance=True, description="Classify a cost review: recurring, one-time, optional, contractual or legally required.")
def classify_cost(ctx: ToolContext, packet_id: str) -> dict:
    with transaction() as conn:
        p = P.get(conn, packet_id)
        sub = None
        if p.subject_type == "subscription" and p.subject_id:
            sub = conn.execute(select(db.subscriptions).where(db.subscriptions.c.id == p.subject_id)).first()
        c = P.classify(vendor=p.vendor, item=p.item, interval=p.interval, amount_minor=p.amount_minor,
                       contract_terms=sub.contract_terms if sub else None, unusual=p.risk == "high" and p.origin == "fee_detected")
        conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == packet_id).values(**c, updated_at=db.utcnow()))
        audit.record(conn, org_id=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="packet.classified",
                     subject_type="cost_review_packet", subject_id=packet_id, detail=c)
    return {"packet_id": packet_id, "status": c["classification"], "action": "escalate" if c["significant"] else "routine"}


def _funding_account(conn, org_id: str, data_mode: str) -> dict:
    acct = conn.execute(select(db.financial_accounts).where(db.financial_accounts.c.organization_id == org_id,
                                                            db.financial_accounts.c.account_type == "credit_card",
                                                            db.financial_accounts.c.data_mode == data_mode)
                        .order_by(db.financial_accounts.c.created_at)).first()
    if acct is None:
        return {"account_ref": "owner-chooses", "label": "You choose the payment method"}
    return {"account_ref": f"acct:{acct.id}", "label": f"{acct.name} ••{acct.mask}"}


@tool("record_cost_findings", finance=True, description="Compare researched options and record the savings analysis for a cost review.")
def record_cost_findings(ctx: ToolContext, packet_id: str) -> dict:
    with transaction() as conn:
        p = P.get(conn, packet_id)
        rec = R.recommend(p, p.findings or [])
        requested = next((f for f in (p.findings or []) if f["is_requested"]), None)
        chosen = next((f for f in (p.findings or []) if rec.get("chosen") and f["vendor"] == rec["chosen"]), None)
        if chosen and requested and not chosen["is_requested"]:
            conn.execute(insert(db.savings_opportunities).values(
                id=db.new_id(), organization_id=ctx.org_id, packet_id=packet_id, title=f"{chosen['vendor']} instead of {p.vendor}",
                current_annual_minor=requested["yearly_minor"], proposed_annual_minor=chosen["yearly_minor"],
                migration_cost_minor=chosen["migration_minor"],
                first_year_saving_minor=requested["first_year_minor"] - chosen["first_year_minor"],
                confidence="low" if chosen["data_mode"] == "fixture" else "medium", alternative=chosen, data_mode=p.data_mode))
        elif rec["action"] == "avoid_fee" and requested:
            conn.execute(insert(db.savings_opportunities).values(
                id=db.new_id(), organization_id=ctx.org_id, packet_id=packet_id, title=f"Avoid the {p.item.lower()}",
                current_annual_minor=requested["yearly_minor"], proposed_annual_minor=0, migration_cost_minor=0,
                first_year_saving_minor=requested["yearly_minor"], confidence="medium", alternative={}, data_mode=p.data_mode))
        conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == packet_id).values(
            recommendation={**(p.recommendation or {}), **rec}, updated_at=db.utcnow()))
        audit.record(conn, org_id=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="analysis.recorded",
                     subject_type="cost_review_packet", subject_id=packet_id, detail={"action": rec["action"], "chosen": rec.get("chosen")})
    return {"packet_id": packet_id, "action": rec["action"]}


@tool("propose_financial_action", finance=True,
      description="Turn the recommendation into exact, expiring approval requests for the owner. Proposes; never executes.")
def propose_financial_action(ctx: ToolContext, packet_id: str) -> dict:
    with transaction() as conn:
        p = P.get(conn, packet_id)
        rec = dict(p.recommendation or {})
        fund = _funding_account(conn, ctx.org_id, p.data_mode)
        options: dict[str, dict] = {}
        by_vendor = {f["vendor"]: f for f in (p.findings or [])}
        requested = next((f for f in (p.findings or []) if f["is_requested"]), None)

        def option(key: str, f: dict) -> None:
            options[key] = {"vendor": f["vendor"], "item": f["item"], "amount_minor": int(f["price_minor"]), "currency": p.currency,
                            "interval": f["interval"], "recipient": f["vendor"], "account_ref": fund["account_ref"],
                            "account_label": fund["label"], "three_year_minor": f["three_year_minor"]}

        if p.origin == "purchase_request":
            if rec.get("action") == "choose_alternative" and rec.get("chosen") in by_vendor:
                option("recommended", by_vendor[rec["chosen"]])
                if requested:
                    option("requested", requested)
            elif requested:
                option("recommended", requested)
        rec["options"] = options
        conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == packet_id).values(recommendation=rec, updated_at=db.utcnow()))
        ids = []
        for key, o in options.items():
            if o["amount_minor"] <= 0 and key != "recommended":
                continue
            ids.append(A.request(conn, org_id=ctx.org_id, packet_id=packet_id, action_type="purchase", amount_minor=o["amount_minor"],
                                 currency=o["currency"], recipient=o["recipient"], account_ref=o["account_ref"],
                                 details={"option": key, "item": o["item"], "interval": o["interval"], "account_label": o["account_label"]},
                                 requested_by_agent_id=ctx.agent_id, data_mode=p.data_mode))
    return {"packet_id": packet_id, "count": len(ids), "status": "proposed" if ids else "no_spend"}


@tool("execute_financial_action", finance_gate=True,
      description="Carry out one owner-approved financial action with exactly the approved terms. Refused otherwise.")
def execute_financial_action(ctx: ToolContext, approval_id: str, action_type: str, amount_minor: int, currency: str, recipient: str,
                             account_ref: str) -> dict:
    with transaction() as conn:
        # Re-checked here too, in the transaction that records the result (the registry already checked once).
        try:
            a = A.authorize_execution(conn, org_id=ctx.org_id, approval_id=approval_id, action_type=action_type,
                                      amount_minor=int(amount_minor), currency=currency, recipient=recipient, account_ref=account_ref)
        except A.ApprovalRefused as exc:
            raise ToolFailed(f"refused: {exc}") from exc
        if a.data_mode != "simulated":
            # No payment rail is connected: the owner completes it. Nothing is charged by the system.
            audit.record(conn, org_id=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="execution.manual_required",
                         subject_type="financial_approval", subject_id=a.id, detail={"reason": "no authorized payment integration"})
            return {"approval_id": approval_id, "status": "manual_required", "data_mode": a.data_mode}
        ref = f"SIM-{db.new_id()[:8]}"
        if not A.mark_executed(conn, a, execution_ref=ref, execution_mode="simulated", actor_type="agent", actor_id=ctx.agent_id):
            raise ToolFailed("refused: this approval was already used")
        p = P.get(conn, a.packet_id) if a.packet_id else None
        acct_id = account_ref.split(":", 1)[1] if account_ref.startswith("acct:") else None
        if acct_id and not _is_uuid(acct_id):
            acct_id = None
        conn_id = conn.execute(select(db.financial_accounts.c.connection_id).where(db.financial_accounts.c.id == acct_id)).scalar() if acct_id else None
        if conn_id and int(amount_minor) > 0:   # a free plan moves no money, so there is no ledger line
            conn.execute(insert(db.financial_transactions).values(
                id=db.new_id(), organization_id=ctx.org_id, connection_id=conn_id, account_id=acct_id, dedupe_key=f"exec:{a.id}",
                external_id=ref, posted_at=db.utcnow(), amount_minor=-int(amount_minor), currency=currency,
                description=f"SIMULATED {a.action_type} approved by owner ({recipient})", merchant=recipient,
                category_key="software" if a.action_type == "purchase" else "bills",
                kind="expense", is_fee=0, recurring=int((a.details or {}).get("interval") in ("month", "year")),
                reconciliation_status="MATCHED", matched_type="financial_approval", matched_id=a.id, data_mode="simulated"))
        if p is not None and (a.details or {}).get("interval") in ("month", "year"):
            exists = conn.execute(select(db.subscriptions.c.id).where(db.subscriptions.c.organization_id == ctx.org_id,
                                                                      db.subscriptions.c.vendor == recipient,
                                                                      db.subscriptions.c.plan == (a.details or {}).get("item"))).first()
            if not exists:
                conn.execute(insert(db.subscriptions).values(
                    id=db.new_id(), organization_id=ctx.org_id, vendor=recipient, plan=(a.details or {}).get("item"), amount_minor=int(amount_minor),
                    currency=currency, interval=a.details["interval"], status="ACTIVE", category_key="software", data_mode="simulated"))
        femit(conn, "finance.action_executed", {"approval_id": a.id, "packet_id": a.packet_id, "action_type": a.action_type,
                                                "data_mode": "simulated", "label": "simulated: no real money moved"},
              agent_id=ctx.agent_id, mission_id=ctx.mission_id, simulated=True)
    return {"approval_id": approval_id, "status": "executed_simulated", "data_mode": "simulated"}
