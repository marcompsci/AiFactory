"""Periodic supervision by deterministic rules (no model calls).

Runs as the durable `supervisor` scheduled job. It never asks Opus whether something is still running; it
reads timestamps and states. Each finding is recorded once as a manager decision + event.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import emit

from . import reliability
from .manager import record_decision
from .release import check_authorization, ReleaseDenied


def _once(conn: Connection, subject_id: str, decision_type: str, outcome: str) -> bool:
    return conn.execute(select(db.manager_decisions.c.id).where(db.manager_decisions.c.subject_id == subject_id,
                                                                db.manager_decisions.c.decision_type == decision_type,
                                                                db.manager_decisions.c.outcome == outcome)).first() is None


def supervise(conn: Connection) -> dict:
    now = datetime.now(timezone.utc)
    found = {"stalled": 0, "looping": 0, "suspended": 0, "drift": 0, "reassigned": 0, "invalidated": 0}

    for t in conn.execute(select(db.tasks).where(db.tasks.c.status == "RUNNING")).fetchall():
        if datetime.fromisoformat(t.updated_at) < now - timedelta(seconds=t.timeout_seconds * 1.5) and _once(conn, t.id, "escalation", "stalled"):
            record_decision(conn, decision_type="escalation", subject_type="task", subject_id=t.id, outcome="stalled",
                            rationale=f"'{t.title}' has been running {int((now - datetime.fromisoformat(t.updated_at)).total_seconds())}s, past 1.5× its timeout.",
                            event="manager.escalation_created")
            found["stalled"] += 1

    # loops: one running task making the same tool call with the same arguments again and again
    for t in conn.execute(select(db.tasks).where(db.tasks.c.status == "RUNNING")).fetchall():
        rep = reliability.repeated_tool_call(conn, t.id)
        if rep and _once(conn, t.id, "escalation", "looping"):
            record_decision(conn, decision_type="escalation", subject_type="task", subject_id=t.id, outcome="looping",
                            rationale=f"'{t.title}' has called {rep[0]} with the same arguments {rep[1]} times. It may be stuck in a loop.",
                            event="manager.loop_detected", org_id=t.organization_id)
            found["looping"] += 1

    for m in conn.execute(select(db.missions).where(db.missions.c.paused == 1)).fetchall():
        if m.pause_reason and "budget" in m.pause_reason.lower() and _once(conn, m.id, "budget_enforcement", "suspended"):
            record_decision(conn, decision_type="budget_enforcement", subject_type="mission", subject_id=m.id, outcome="suspended",
                            rationale=f"Mission suspended: {m.pause_reason}. Raising the limit is the owner's call.",
                            event="manager.escalation_created")
            found["suspended"] += 1

    # goal drift: compare what was built with the approved specification
    rows = conn.execute(select(db.tasks, db.opportunities.c.spec.label("spec")).join(db.missions, db.missions.c.id == db.tasks.c.mission_id)
                        .join(db.opportunities, db.opportunities.c.id == db.missions.c.opportunity_id)
                        .where(db.tasks.c.key == "scaffold", db.tasks.c.status == "COMPLETED")).fetchall()
    for r in rows:
        if conn.execute(select(db.goal_checkpoints.c.id).where(db.goal_checkpoints.c.mission_id == r.mission_id,
                                                           db.goal_checkpoints.c.status.in_(["drift", "on_track"]))).first():
            continue
        spec, out = r.spec or {}, r.outputs or {}
        issues = []
        if out.get("app_name") != (spec.get("app_name") or "")[:30]:
            issues.append(f"name '{out.get('app_name')}' differs from spec '{spec.get('app_name')}'")
        missing = [f for f in spec.get("features", []) if f not in (out.get("features") or [])]
        if missing:
            issues.append(f"missing features {missing}")
        status = "drift" if issues else "on_track"
        conn.execute(insert(db.goal_checkpoints).values(id=db.new_id(), organization_id=r.organization_id, mission_id=r.mission_id,
                                                        status=status, findings=issues or ["output matches the approved spec"]))
        record_decision(conn, decision_type="drift_check", subject_type="mission", subject_id=r.mission_id, outcome=status,
                        rationale="; ".join(issues) or "Build matches the approved specification.",
                        event="manager.escalation_created" if issues else None)
        found["drift"] += bool(issues)

    # reassignment: a pending task whose agent is busy elsewhere goes to an idle peer with the same permissions
    for t in conn.execute(select(db.tasks).where(db.tasks.c.status == "PENDING")).fetchall():
        if datetime.fromisoformat(t.updated_at) > now - timedelta(seconds=30):
            continue
        a = conn.execute(select(db.agents).where(db.agents.c.id == t.agent_id)).first()
        if a.execution_state in ("IDLE", "COMPLETED", "FAILED", "CANCELLED"):
            continue
        peers = conn.execute(select(db.agents).where(db.agents.c.department_id == a.department_id, db.agents.c.id != a.id,
                                                     db.agents.c.execution_state == "IDLE")).fetchall()
        for p in peers:
            caps = {c.tool_name for c in conn.execute(select(db.agent_capabilities.c.tool_name).where(db.agent_capabilities.c.agent_id == p.id))}
            if set(t.permitted_tools or []) <= caps:
                conn.execute(update(db.tasks).where(db.tasks.c.id == t.id).values(agent_id=p.id, updated_at=db.utcnow()))
                record_decision(conn, decision_type="reassignment", subject_type="task", subject_id=t.id, outcome=f"to:{p.key}",
                                rationale=f"{a.name} is busy; {p.name} in the same department has every permission the task needs.")
                found["reassigned"] += 1
                break

    # release integrity: approvals stay valid only while the approved bytes are unchanged
    for auth in conn.execute(select(db.release_authorizations)).fetchall():
        if conn.execute(select(db.release_invalidations.c.id).where(db.release_invalidations.c.authorization_id == auth.id)).first():
            continue
        try:
            check_authorization(conn, auth.organization_id, auth.id, None)
        except ReleaseDenied:
            found["invalidated"] += 1
    return found
