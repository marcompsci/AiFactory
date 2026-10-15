"""V5.1 investigation tools: research, scoring, sandboxed evaluation, QA review. Read-only with respect to money
and accounts; `_check_investigation` in the registry confines them to owner-requested investigations."""
from __future__ import annotations

from sqlalchemy import select

from services.core import db
from services.core.events import transaction
from services.tools.registry import ToolContext, ToolFailed, tool

from . import alt_research as R
from . import audit
from . import investigations as I
from . import packets as P


@tool("investigate_alternatives", investigation=True, description="Find up to five legitimate alternatives, each with attributed evidence.")
def investigate_alternatives(ctx: ToolContext, investigation_id: str) -> dict:
    with transaction() as conn:
        inv = I.get(conn, investigation_id)
        n = R.gather(conn, inv)
        audit.record(conn, org_id=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="investigation.candidates_found",
                     subject_type="savings_investigation", subject_id=investigation_id, detail={"count": n, "category": inv.category,
                                                                                                "data_mode": "fixture"})
    return {"investigation_id": investigation_id, "count": n, "data_mode": "fixture"}


@tool("score_alternatives", investigation=True, description="Score candidates on compatibility, security, functionality, migration and cost.")
def score_alternatives(ctx: ToolContext, investigation_id: str) -> dict:
    with transaction() as conn:
        inv = I.get(conn, investigation_id)
        shortlist = R.score(conn, inv, P.get(conn, inv.packet_id), ctx.agent_id)
        audit.record(conn, org_id=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="investigation.scored",
                     subject_type="savings_investigation", subject_id=investigation_id,
                     detail={"shortlist": [s["name"] for s in shortlist], "top_score": shortlist[0]["total"] if shortlist else None})
    return {"investigation_id": investigation_id, "count": len(shortlist), "status": "shortlisted"}


@tool("sandbox_evaluate_candidate", investigation=True,
      description="Test the strongest candidate against the owner's requirements in a disposable, isolated sandbox.")
def sandbox_evaluate_candidate(ctx: ToolContext, investigation_id: str) -> dict:
    with db.get_engine().connect() as conn:
        inv = I.get(conn, investigation_id)
        top = conn.execute(select(db.alternative_candidates).where(db.alternative_candidates.c.id == inv.top_candidate_id)).first() \
            if inv.top_candidate_id else None
    if top is None:
        raise ToolFailed("no shortlisted candidate to evaluate")
    try:
        r = R.run_sandbox(transaction, inv, top, ctx.mission_id)
    except PermissionError as exc:
        raise ToolFailed(str(exc)) from exc
    with transaction() as conn:
        audit.record(conn, org_id=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="investigation.sandbox_evaluated",
                     subject_type="savings_investigation", subject_id=investigation_id,
                     detail={"candidate": top.name, "status": r["status"], "passed": r["passed"], "failed": r["failed"], "errors": r["errors"]})
    return {"investigation_id": investigation_id, **{k: r[k] for k in ("status", "passed", "failed", "errors")}}


@tool("review_sandbox_evidence", investigation=True, description="QA review of the sandbox evidence for an investigation.")
def review_sandbox_evidence(ctx: ToolContext, investigation_id: str) -> dict:
    with transaction() as conn:
        r = R.qa_review(conn, I.get(conn, investigation_id), ctx.agent_id)
        audit.record(conn, org_id=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="investigation.qa_reviewed",
                     subject_type="savings_investigation", subject_id=investigation_id, detail={"verdict": r["verdict"]})
    return {"investigation_id": investigation_id, "verdict": r["verdict"]}
