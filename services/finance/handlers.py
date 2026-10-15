"""Task handlers for the bank's mission kinds. Messages between agents are visible in the city, so they name the
work, never the money (THREAT_MODEL F9). Model calls see only the redacted view (F8)."""
from __future__ import annotations

import json

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.orchestrator.handlers import TaskEnv, TaskError

from . import packets as P
from .redaction import for_model, round_amount


def _packet_id(env: TaskEnv) -> str:
    pid = (env.mission.params or {}).get("packet_id")
    if not pid:
        raise TaskError("mission has no cost review attached")
    return pid


def request_tool(env: TaskEnv) -> dict:
    p = env.mission.params or {}
    r = env.tool("request_purchase", vendor=p["vendor"], item=p["item"], amount_minor=int(p["amount_minor"]), interval=p["interval"],
                 justification=p.get("justification", ""), currency=p.get("currency", "USD"))
    env.say("Sent a paid-tool request to the AI Central Bank. Nothing is bought until the owner approves it.", to_key="cfo", kind="handoff")
    return {"packet_id": r["packet_id"]}


def research_costs(env: TaskEnv) -> dict:
    pid = _packet_id(env)
    r = env.tool("research_cost_alternatives", packet_id=pid)
    note = None
    if env.live and r["count"]:
        with db.get_engine().connect() as conn:
            pkt = P.get(conn, pid)
        options = [{"vendor": f["vendor"], "compatibility": f["compatibility"], "security": f["security"], "quality": f["quality"],
                    "approx_yearly": round_amount(f["yearly_minor"]), "notes": f["notes"]} for f in (pkt.findings or [])]
        note = env.ask_model(
            "You are a research analyst. In at most three sentences, compare these options for a small software business. "
            "Do not invent prices or facts beyond what is given.\n<untrusted>"
            + json.dumps({"request": r["redacted_view"], "options": options}) + "</untrusted>", 220)
        with transaction() as conn:
            pkt = P.get(conn, pid)
            conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == pid)
                         .values(recommendation={**(pkt.recommendation or {}), "research_note": note, "research_note_model": env.agent.model_name}))
    env.say(f"Researched {r['count']} option(s) from authorized sources ({r['data_mode']} data). Findings are going back to the bank.",
            to_key="savings_strategist", kind="handoff")
    return {"count": r["count"], "data_mode": r["data_mode"]}


def analyze_costs(env: TaskEnv) -> dict:
    pid = _packet_id(env)
    env.tool("read_ledger_summary")
    r = env.tool("record_cost_findings", packet_id=pid)
    env.say(f"Analysis done: {r['action'].replace('_', ' ')}.", to_key="cfo", kind="handoff")
    return {"action": r["action"]}


def recommend_cost(env: TaskEnv) -> dict:
    pid = _packet_id(env)
    c = env.tool("classify_cost", packet_id=pid)
    r = env.tool("propose_financial_action", packet_id=pid)
    with db.get_engine().connect() as conn:
        pkt = P.get(conn, pid)
    rec = dict(pkt.recommendation or {})
    if env.live:
        view = for_model(vendor=pkt.vendor, item=pkt.item, category=pkt.classification, amount_minor=pkt.amount_minor, interval=pkt.interval)
        rec["narrative"] = env.ask_model(
            "You are a careful CFO. In two sentences, explain this recommendation to the owner. Never suggest skipping legal, "
            "contractual or tax obligations, and never claim money has been spent.\n<untrusted>"
            + json.dumps({"request": view, "recommendation": rec.get("summary"), "action": rec.get("action")}) + "</untrusted>", 200)
        rec["narrative_model"] = env.agent.model_name
    else:
        rec["narrative"] = f"[simulation · templated text] {rec.get('summary', '')}"
    with transaction() as conn:
        conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == pid).values(recommendation=rec))
    env.say("Recommendation ready" + (", escalating to the General Manager." if pkt.significant else ", sending it to the owner."),
            to_key="general_manager" if pkt.significant else None, kind="handoff")
    return {"classification": c["status"], "approval_requests": r["count"]}


def execute_action(env: TaskEnv) -> dict:
    aid = (env.mission.params or {}).get("approval_id")
    with db.get_engine().connect() as conn:
        a = conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.id == aid)).first()
    if a is None:
        raise TaskError("no approval attached to this mission")
    r = env.tool("execute_financial_action", approval_id=a.id, action_type=a.action_type, amount_minor=a.amount_minor, currency=a.currency,
                 recipient=a.recipient, account_ref=a.account_ref)
    if r["status"] == "manual_required":
        env.say("Owner approved. No payment integration is connected, so the owner completes this purchase personally.", kind="status")
    else:
        env.say("Owner-approved action recorded (simulated data: no real money moved).", kind="status")
    return {"status": r["status"]}


FINANCE_HANDLERS = {"request_tool": request_tool, "research_costs": research_costs, "analyze_costs": analyze_costs,
                    "recommend_cost": recommend_cost, "execute_action": execute_action}


# ------------------------------------------------------------------ V5.1 free-alternative investigation
def _inv(env: TaskEnv) -> str:
    inv = (env.mission.params or {}).get("investigation_id")
    if not inv:
        raise TaskError("mission has no investigation attached")
    return inv


def alt_research(env: TaskEnv) -> dict:
    r = env.tool("investigate_alternatives", investigation_id=_inv(env))
    env.say(f"Found {r['count']} candidate(s) from authorized sources ({r['data_mode']} data); sending the shortlist to the bank.",
            to_key="savings_strategist", kind="handoff")
    return {"count": r["count"]}


def alt_evaluation(env: TaskEnv) -> dict:
    r = env.tool("score_alternatives", investigation_id=_inv(env))
    env.say(f"Scored the candidates; {r['count']} on the shortlist. Code Forge will test the strongest one.", to_key="developer", kind="handoff")
    return {"shortlist": r["count"]}


def alt_sandbox(env: TaskEnv) -> dict:
    r = env.tool("sandbox_evaluate_candidate", investigation_id=_inv(env))
    env.say(f"Sandbox evaluation {r['status'].lower()}: {r['passed']} passed, {r['failed']} failed, {r['errors']} errors. Evidence to QA.",
            to_key="qa", kind="handoff")
    return {"status": r["status"], "passed": r["passed"], "failed": r["failed"]}


def alt_qa(env: TaskEnv) -> dict:
    r = env.tool("review_sandbox_evidence", investigation_id=_inv(env))
    env.say(f"QA verdict: {r['verdict'].replace('_', ' ')}. Sending the investigation to the General Manager.", to_key="general_manager",
            kind="handoff")
    return {"verdict": r["verdict"]}


FINANCE_HANDLERS.update({"alt_research": alt_research, "alt_evaluation": alt_evaluation, "alt_sandbox": alt_sandbox, "alt_qa": alt_qa})
