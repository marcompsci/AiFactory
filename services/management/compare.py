"""Compare runs (V6.31): a mission next to the run before it, from the records.

"The run before" is, in order: the mission it was started again from, the previous run of the same
schedule, or else the latest earlier mission of the same kind with the same request. You can also name the other
mission. Everything is counted from the records; cost is the gateway's estimate.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from services.core import db

from .reliability import objective_for

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


def _ts(v) -> datetime | None:
    if not v:
        return None
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def summary(conn: Connection, m) -> dict:
    T, U = db.tasks, db.usage_records
    steps = dict(conn.execute(select(T.c.status, func.count()).where(T.c.mission_id == m.id).group_by(T.c.status)).fetchall())
    usd, calls = conn.execute(select(func.coalesce(func.sum(U.c.estimated_cost_usd), 0.0), func.count())
                              .where(U.c.mission_id == m.id)).first()
    start, end = _ts(m.created_at), _ts(m.updated_at)
    obj = objective_for(conn, m.id)
    return {"id": m.id, "title": m.title, "status": m.status, "outcome": m.outcome, "failure_reason": m.failure_reason,
            "execution_mode": m.execution_mode, "created_at": m.created_at,
            "duration_s": int((end - start).total_seconds()) if start and end and m.status in TERMINAL else None,
            "cost_usd": round(float(usd or 0), 4), "ai_calls": int(calls or 0),
            "steps": {"total": sum(steps.values()), "completed": int(steps.get("COMPLETED", 0)), "failed": int(steps.get("FAILED", 0))},
            "objective": obj["status"] if obj else None}


def previous(conn: Connection, org: str, m) -> tuple[str | None, str]:
    """(mission id, how it was found) for the run before `m`."""
    L, R, M = db.mission_links, db.schedule_runs, db.missions
    link = conn.execute(select(L.c.from_mission_id).where(L.c.organization_id == org, L.c.to_mission_id == m.id,
                                                          L.c.kind == "rerun")).first()
    if link:  # (a follow-on is different work, so it's not "the run before")
        return link.from_mission_id, "started again from"
    run = conn.execute(select(R.c.schedule_id, R.c.started_at).where(R.c.organization_id == org, R.c.mission_id == m.id)).first()
    if run:
        prior = conn.execute(select(R.c.mission_id).where(R.c.schedule_id == run.schedule_id, R.c.started_at < run.started_at)
                             .order_by(R.c.started_at.desc()).limit(1)).scalar()
        if prior:
            return prior, "the schedule's previous run"
    prior = conn.execute(select(M.c.id).where(M.c.organization_id == org, M.c.kind == m.kind, M.c.prompt == m.prompt,
                                              M.c.created_at < m.created_at, M.c.id != m.id)
                         .order_by(M.c.created_at.desc()).limit(1)).scalar()
    return (prior, "the previous run of the same request") if prior else (None, "")


def _dur(s: int | None) -> str:
    if s is None:
        return "still going"
    return f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


def changes(a: dict, b: dict) -> list[str]:
    """Plain sentences for what differs, `b` (before) → `a` (this run)."""
    out = []
    if a["status"] != b["status"]:
        out.append(f"Status: {b['status'].lower()} → {a['status'].lower()}")
    if a["objective"] != b["objective"]:
        out.append(f"Objective: {(b['objective'] or 'not checked').replace('objective_', '').replace('_', ' ')} → "
                   f"{(a['objective'] or 'not checked').replace('objective_', '').replace('_', ' ')}")
    if a["cost_usd"] != b["cost_usd"]:
        pct = f" ({round((a['cost_usd'] - b['cost_usd']) / b['cost_usd'] * 100):+d}%)" if b["cost_usd"] else ""
        out.append(f"Estimated cost: ${b['cost_usd']:.2f} → ${a['cost_usd']:.2f}{pct}")
    if a["duration_s"] != b["duration_s"]:
        out.append(f"Time taken: {_dur(b['duration_s'])} → {_dur(a['duration_s'])}")
    if a["steps"]["failed"] != b["steps"]["failed"]:
        out.append(f"Failed steps: {b['steps']['failed']} → {a['steps']['failed']}")
    if a["execution_mode"] != b["execution_mode"]:
        out.append(f"Mode: {b['execution_mode']} → {a['execution_mode']}")
    return out or ["No difference in status, objective, cost, time or steps."]


def compare(conn: Connection, org: str, mission_id: str, other_id: str | None = None) -> dict | None:
    M = db.missions
    m = conn.execute(select(M).where(M.c.id == mission_id, M.c.organization_id == org)).first()
    if m is None:
        return None
    how = "chosen by you"
    if other_id is None:
        other_id, how = previous(conn, org, m)
    o = conn.execute(select(M).where(M.c.id == other_id, M.c.organization_id == org)).first() if other_id else None
    this = summary(conn, m)
    if o is None:
        return {"this": this, "before": None, "how": None, "changes": [], "note": "There's no earlier run of this to compare with."}
    before = summary(conn, o)
    return {"this": this, "before": before, "how": how, "changes": changes(this, before), "is_estimate": True}
