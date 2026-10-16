"""Recovery plans: after a mission fails, the General Manager drafts the next attempt, and it runs only if you approve.

Magentic-One's outer loop replans when progress stalls; a plan that changes nothing just repeats the failure. Here
the plan is chosen by rules from the failure's MAST label (services/management/reliability.py), so it answers what
actually went wrong, and it carries the agent's cited lesson into the new mission's instructions. Nothing starts on
its own: a plan is a proposal in the Owner's Tower until you approve or decline it, and plans stop after two
recoveries in a row so a bad mission can't loop through the owner forever.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import emit

from . import charter, reliability

KINDS = {"fix_failing_test"}  # missions created from your own words; others are restarted by their own pipelines
MAX_DEPTH = 2
EXPIRES_AFTER = timedelta(days=7)
MAX_USD = 50.0


def _failure(conn: Connection, m) -> tuple[str, str, str]:
    """(mode, the failed step's title, its error) for the mission's first failed task."""
    errors = reliability._task_errors(conn, org_id=m.organization_id, mission_id=m.id)
    for t in conn.execute(select(db.tasks).where(db.tasks.c.mission_id == m.id, db.tasks.c.status == "FAILED")
                          .order_by(db.tasks.c.ordinal)).fetchall():
        run = conn.execute(select(db.task_runs.c.error).where(db.task_runs.c.task_id == t.id, db.task_runs.c.status == "FAILED")
                           .order_by(db.task_runs.c.attempt.desc())).first()
        err = errors.get(t.id) or (run.error if run else "") or ""
        under = run.error if run and run.error else err
        mode = reliability._mode_for(err)
        if mode == "FM-1.3":  # a stopped loop: plan for what it kept failing at
            inner = reliability._mode_for(under)
            mode = inner if inner not in ("UNK",) else mode
        return mode, t.title, reliability._short(under or err)
    reason = m.failure_reason or ""
    return reliability._mode_for(reason), "", reliability._short(reason)


def _depth(conn: Connection, mission_id: str) -> int:
    """How many recoveries led to this mission (0 for a mission you started yourself)."""
    parent = conn.execute(select(db.recovery_plans.c.params).where(db.recovery_plans.c.new_mission_id == mission_id)).first()
    return int((parent.params or {}).get("recovery_depth") or 0) if parent else 0


def propose(conn: Connection, mission_id: str) -> dict | None:
    """Draft a plan for a failed mission (idempotent: one pending plan per mission)."""
    m = conn.execute(select(db.missions).where(db.missions.c.id == mission_id)).first()
    if m is None or m.status != "FAILED" or m.kind not in KINDS:
        return None
    if conn.execute(select(db.recovery_plans.c.id).where(db.recovery_plans.c.mission_id == mission_id)).first():
        return None
    mode, step, err = _failure(conn, m)
    depth = _depth(conn, m.id) + 1
    lessons = []
    for t in conn.execute(select(db.tasks.c.agent_id, db.tasks.c.key).where(db.tasks.c.mission_id == mission_id,
                                                                             db.tasks.c.status == "FAILED")).fetchall():
        lessons += [l["lesson"] for l in reliability.lessons_for(conn, t.agent_id, t.key, limit=1)]
    base = m.prompt.split("\n\nRecovery notes", 1)[0]
    cap = charter.rules(conn, m.organization_id).get("mission_budget_cap_usd")
    budget = m.budget_usd
    where = f" at \"{step}\"" if step else ""

    def guided(lines: list[str]) -> str:
        notes = "\n".join(f"- {x}" for x in lines + [f"Lesson: {l}" for l in lessons[:2]])
        return f"{base}\n\nRecovery notes from the last attempt (it failed{where}: {err}):\n{notes}"[:4000]

    if depth > MAX_DEPTH:
        strategy, summary = "none", "Two recoveries in a row have failed. Read the trace before trying again."
        rationale, prompt = f"Stopping here so a failing mission doesn't loop: this would be recovery {depth}.", None
    elif mode == "INFRA":
        strategy, summary = "retry_later", "Run the same mission again once the AI provider is answering."
        rationale, prompt = f"It failed{where} because a model or tool was unavailable ({err}), not because of the plan.", base
    elif mode == "RES":
        new = round(min(budget * 2, cap if cap is not None else MAX_USD, MAX_USD), 2)
        if new <= budget:
            strategy, summary = "none", "It needs more budget than your charter allows. Raise the cap first if you want it to run."
            rationale, prompt = f"Budget ${budget:.2f} is already at the limit.", None
        else:
            strategy, summary = "raise_budget", f"Run it again with a ${new:.2f} budget (was ${budget:.2f})."
            rationale, prompt, budget = f"It ran out of budget{where}: {err}.", base, new
    elif mode == "FM-1.2":
        strategy, summary = "retry_with_guidance", "Try again with an explicit rule: fix the source code, never edit the tests."
        rationale = f"The developer tried to work outside its role{where} ({err})."
        prompt = guided(["Fix the source code under test. Do not modify any test file to make tests pass."])
    elif mode in ("FM-1.1", "FM-1.3"):
        strategy, summary = "retry_with_guidance", "Try a different fix, starting from what QA reported last time."
        rationale = f"The same approach kept failing{where} ({err}); retrying unchanged would repeat it."
        prompt = guided(["The previous fix did not pass QA. Read the failing test output first and change the approach."])
    elif mode == "FM-1.5":
        strategy, summary = "narrow_scope", "Try again with a narrower change, one file at a time."
        rationale = f"A step ran out of time{where} ({err})."
        prompt = guided(["Keep the change as small as possible: one function in one file, then stop."])
    elif mode == "FM-2.6":
        strategy, summary = "retry_with_guidance", "Try again, insisting on the exact answer format."
        rationale = f"An answer didn't match the format the step needed{where} ({err})."
        prompt = guided(["Answer only in the exact JSON format the step asks for, with no extra text."])
    else:
        strategy, summary = "none", "No safe automatic recovery for this failure. Read the trace to decide."
        rationale, prompt = f"The failure{where} didn't match a known pattern: {err or 'no error recorded'}.", None

    params = {"prompt": prompt, "title": f"Recovery: {m.title}"[:120], "budget_usd": budget, "repository_id": m.repository_id,
              "recovery_of": m.id, "recovery_depth": depth} if prompt else {"recovery_of": m.id, "recovery_depth": depth}
    pid = db.new_id()
    conn.execute(insert(db.recovery_plans).values(id=pid, organization_id=m.organization_id, mission_id=m.id, failure_mode=mode,
                                                  strategy=strategy, summary=summary, rationale=rationale, params=params,
                                                  status="PENDING" if prompt else "INFO"))
    from .manager import record_decision
    record_decision(conn, decision_type="escalation", subject_type="mission", subject_id=m.id, outcome=f"recovery:{strategy}",
                    rationale=f"{summary} {rationale}", org_id=m.organization_id)
    emit(conn, "recovery.proposed", mission_id=m.id, execution_mode=m.execution_mode, org_id=m.organization_id,
         payload={"plan_id": pid, "strategy": strategy, "failure_mode": mode, "summary": summary, "actionable": bool(prompt)})
    return plan(conn, pid)


def plan(conn: Connection, plan_id: str) -> dict | None:
    r = conn.execute(select(db.recovery_plans, db.missions.c.title.label("mission_title"))
                     .join(db.missions, db.missions.c.id == db.recovery_plans.c.mission_id)
                     .where(db.recovery_plans.c.id == plan_id)).first()
    if r is None:
        return None
    d = dict(r._mapping)
    d["actionable"] = bool((d.get("params") or {}).get("prompt"))
    d["mode_name"] = reliability.MODES.get(d["failure_mode"], ("", ""))[1]
    return d


def plans(conn: Connection, org_id: str, status: str | None = None, mission_id: str | None = None) -> list[dict]:
    q = select(db.recovery_plans.c.id).where(db.recovery_plans.c.organization_id == org_id)
    if status:
        q = q.where(db.recovery_plans.c.status == status)
    if mission_id:
        q = q.where(db.recovery_plans.c.mission_id == mission_id)
    return [plan(conn, r.id) for r in conn.execute(q.order_by(db.recovery_plans.c.created_at.desc()).limit(50)).fetchall()]


def decide(conn: Connection, plan_id: str, *, user_id: str, approve: bool, new_mission_id: str | None = None) -> None:
    status = "APPROVED" if approve else "DECLINED"
    conn.execute(update(db.recovery_plans).where(db.recovery_plans.c.id == plan_id)
                 .values(status=status, decided_by=user_id, decided_at=db.utcnow(), new_mission_id=new_mission_id))
    p = plan(conn, plan_id)
    emit(conn, "recovery.decided", mission_id=p["mission_id"], org_id=p["organization_id"],
         payload={"plan_id": plan_id, "status": status, "new_mission_id": new_mission_id})


def expire(conn: Connection) -> int:
    cutoff = (datetime.now(timezone.utc) - EXPIRES_AFTER).isoformat()
    res = conn.execute(update(db.recovery_plans).where(db.recovery_plans.c.status == "PENDING", db.recovery_plans.c.created_at < cutoff)
                       .values(status="EXPIRED", decided_at=db.utcnow()))
    return res.rowcount or 0
